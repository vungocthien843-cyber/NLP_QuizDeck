"""Máy worker: nhận PDF sinh viên tải lên trang online (Vercel + Supabase), chạy pipeline đầy đủ ở máy này
(bge-m3, ViT5, NLI, reranker, có GPU càng nhanh), rồi đẩy kết quả lên Supabase.

Chạy trong container (cùng image với api, xem service `worker` trong docker-compose.yml):
    docker compose --profile worker up -d                                   # máy chỉ có CPU
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile worker up -d --build   # máy có GPU

Máy worker chỉ cần mạng chiều ra (không mở cổng, không cần IP tĩnh): nó tự hỏi Supabase xem có việc mới không.

Vòng đời một việc (bảng upload_jobs trên Supabase, migrations/101_upload_jobs.sql của rag-quiz-lite):
    awaiting_file → pending (trình duyệt đã tải PDF lên Storage) → processing (worker nhận) → ready | failed

Biến môi trường (file .env.sync, KHÔNG commit): CLOUD_DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY,
STORAGE_BUCKET. LOCAL_DATABASE_URL và LOCAL_DATA_DIR do docker-compose.yml đặt sẵn.
Tuỳ chọn: WORKER_ID (mặc định tên máy), WORKER_MAX_PAGES (mặc định 60).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import fitz
import httpx
import psycopg

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.pipeline import run_pipeline
from app.models import Document
from tools.sync_to_cloud import TABLES, dsn, env, sync_documents

log = logging.getLogger("worker")

WORKER_ID = os.environ.get("WORKER_ID") or socket.gethostname()
MAX_PAGES = int(os.environ.get("WORKER_MAX_PAGES", "60"))
POLL_SECONDS = 5           # khi rảnh: bao lâu hỏi Supabase một lần
HEARTBEAT_SECONDS = 15     # trang web coi worker "đang bật" nếu nhịp tim mới hơn 2 phút


def device_name() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return f"cuda ({torch.cuda.get_device_name(0)})"
    except Exception:          # noqa: BLE001 - chỉ để hiển thị
        pass
    return "cpu"


class JobFailed(Exception):
    """Lỗi có thông báo dễ hiểu cho sinh viên (ghi vào upload_jobs.error)."""


# ---------------------------------------------------------------- Supabase (DB + Storage)

def cloud_connect(autocommit: bool = True) -> psycopg.Connection:
    # prepare_threshold=None: pooler của Supabase không giữ prepared statement giữa các lần
    return psycopg.connect(dsn("CLOUD_DATABASE_URL"), prepare_threshold=None, autocommit=autocommit)


def local_connect() -> psycopg.Connection:
    return psycopg.connect(dsn("LOCAL_DATABASE_URL"))


class Storage:
    def __init__(self) -> None:
        key = env("SUPABASE_SERVICE_KEY")
        self.base = env("SUPABASE_URL").rstrip("/") + "/storage/v1/object"
        self.bucket = os.environ.get("STORAGE_BUCKET", "slides")
        headers = {"apikey": key}
        if not key.startswith("sb_"):            # khoá kiểu mới sb_secret_... chỉ gửi qua apikey
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.Client(timeout=120, headers=headers)

    def download(self, key: str, dest: Path) -> None:
        r = self.client.get(f"{self.base}/authenticated/{self.bucket}/{quote(key)}")
        if r.status_code == 404 or r.status_code == 400:
            raise JobFailed("Không tìm thấy file trên kho lưu trữ (có thể tải lên chưa xong). Hãy tải lại.")
        r.raise_for_status()
        dest.write_bytes(r.content)

    def remove(self, key: str) -> None:
        try:
            self.client.request("DELETE", f"{self.base}/{self.bucket}", json={"prefixes": [key]})
        except httpx.HTTPError:
            log.warning("Không xoá được %s trên Storage (bỏ qua)", key)


def heartbeat(cloud: psycopg.Connection, device: str) -> None:
    cloud.execute("INSERT INTO worker_heartbeats (worker_id, seen_at, device) VALUES (%s, now(), %s) "
                  "ON CONFLICT (worker_id) DO UPDATE SET seen_at = now(), device = EXCLUDED.device",
                  (WORKER_ID, device))


def requeue_own(cloud: psycopg.Connection) -> None:
    """Worker khởi động lại thì việc đang làm dở bị mất (giống app/main.py): trả về hàng đợi."""
    n = cloud.execute("UPDATE upload_jobs SET status = 'pending', stage = NULL, worker_id = NULL, claimed_at = NULL "
                      "WHERE status = 'processing' AND worker_id = %s", (WORKER_ID,)).rowcount
    if n:
        log.info("Trả %d việc làm dở về hàng đợi", n)


def claim(cloud: psycopg.Connection) -> tuple | None:
    """Nhận việc cũ nhất đang chờ. SKIP LOCKED: nhiều worker chạy cùng lúc cũng không nhận trùng."""
    return cloud.execute(
        "UPDATE upload_jobs SET status = 'processing', worker_id = %s, claimed_at = now(), stage = 'queued', "
        "error = NULL WHERE id = (SELECT id FROM upload_jobs WHERE status = 'pending' ORDER BY created_at "
        "FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id, user_id, filename, storage_key",
        (WORKER_ID,)).fetchone()


def set_job(cloud: psycopg.Connection, job_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = %s" for k in fields)
    extra = ", finished_at = now()" if fields.get("status") in ("ready", "failed") else ""
    cloud.execute(f"UPDATE upload_jobs SET {sets}{extra} WHERE id = %s", (*fields.values(), job_id))


# ---------------------------------------------------------------- xử lý một việc

def bump_local_sequences(local: psycopg.Connection, cloud: psycopg.Connection) -> None:
    """Đồng bộ giữ nguyên id, nên id cấp ở máy này không được trùng id đã có trên Supabase.
    Đẩy sequence cục bộ lên trên max(id) của cả hai bên: máy mới với DB trống vẫn chạy đúng."""
    for t in TABLES:
        cloud_max = cloud.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0]
        seq = local.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,)).fetchone()[0]
        local_max = local.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0]
        last = local.execute(f"SELECT last_value FROM {seq}").fetchone()[0]
        local.execute("SELECT setval(%s, %s, true)", (seq, max(cloud_max, local_max, last, 1)))
    local.commit()


def check_pdf(path: Path) -> None:
    if path.read_bytes()[:5] != b"%PDF-":
        raise JobFailed("File tải lên không phải PDF hợp lệ.")
    try:
        with fitz.open(path) as pdf:
            pages = pdf.page_count
    except Exception as exc:  # noqa: BLE001
        raise JobFailed("Không mở được file PDF (file hỏng hoặc có mật khẩu).") from exc
    if pages == 0:
        raise JobFailed("File PDF không có trang nào.")
    if pages > MAX_PAGES:
        raise JobFailed(f"File có {pages} trang, vượt giới hạn {MAX_PAGES} trang. Hãy tách nhỏ bài giảng.")


def local_status(doc_id: int) -> tuple[str, str | None]:
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        return doc.status, doc.error


def process(cloud: psycopg.Connection, storage: Storage, device: str, job: tuple) -> None:
    job_id, user_id, filename, key = job
    log.info("Nhận việc #%s: %s", job_id, filename)
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.upload_dir / f"{uuid.uuid4().hex}.pdf"

    set_job(cloud, job_id, stage="downloading")
    storage.download(key, dest)
    check_pdf(dest)

    with local_connect() as local:
        bump_local_sequences(local, cloud)
    with SessionLocal() as db:
        doc = Document(filename=filename, file_path=str(dest), source_type="slide", is_shared=False)
        db.add(doc)
        db.commit()
        doc_id = doc.id
    log.info("Việc #%s → tài liệu cục bộ [%s]", job_id, doc_id)

    # Pipeline chạy ở luồng phụ; luồng chính báo tiến độ lên Supabase và giữ nhịp tim
    t = threading.Thread(target=run_pipeline, args=(doc_id,), daemon=True)
    t.start()
    last_stage, last_beat = None, 0.0
    while t.is_alive():
        t.join(timeout=POLL_SECONDS)
        stage, _ = local_status(doc_id)
        if stage != last_stage and stage not in ("ready", "failed"):
            set_job(cloud, job_id, stage=stage)
            last_stage = stage
        if time.monotonic() - last_beat > HEARTBEAT_SECONDS:
            heartbeat(cloud, device)
            last_beat = time.monotonic()

    status, error = local_status(doc_id)
    if status != "ready":
        log.error("Việc #%s thất bại ở pipeline: %s", job_id, error)
        raise JobFailed(f"Xử lý slide thất bại: {(error or 'không rõ lỗi')[:300]}")

    set_job(cloud, job_id, stage="syncing")
    data_dir = Path(os.environ.get("LOCAL_DATA_DIR", str(settings.data_dir))).resolve()
    with local_connect() as local, cloud_connect(autocommit=False) as cl:
        sync_documents(local, cl, [doc_id], data_dir)
        # Slide riêng của người tải lên: access.py chỉ cho chủ sở hữu xem
        cl.execute("UPDATE documents SET owner_user_id = %s, is_shared = false, is_active = true WHERE id = %s",
                   (user_id, doc_id))
        cl.commit()
    set_job(cloud, job_id, status="ready", stage=None, document_id=doc_id, error=error)   # error = cảnh báo nếu có
    storage.remove(key)          # bản gốc đã có ở <doc_id>/source.pdf
    log.info("Xong việc #%s → tài liệu [%s]", job_id, doc_id)


# ---------------------------------------------------------------- vòng lặp chính

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    device = device_name()
    log.info("Worker %s khởi động, thiết bị: %s", WORKER_ID, device)
    storage = Storage()
    cloud = None
    last_beat = 0.0
    while True:
        try:
            if cloud is None or cloud.closed:
                cloud = cloud_connect()
                if not cloud.execute("SELECT to_regclass('public.upload_jobs')").fetchone()[0]:
                    raise SystemExit("DB online chưa chạy migrations/101_upload_jobs.sql")
                requeue_own(cloud)
            if time.monotonic() - last_beat > HEARTBEAT_SECONDS:
                heartbeat(cloud, device)
                last_beat = time.monotonic()
            job = claim(cloud)
            if job is None:
                time.sleep(POLL_SECONDS)
                continue
            try:
                process(cloud, storage, device, job)
            except JobFailed as exc:
                set_job(cloud, job[0], status="failed", stage=None, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - lỗi bất ngờ: ghi lại, worker vẫn chạy tiếp
                log.exception("Việc #%s lỗi", job[0])
                set_job(cloud, job[0], status="failed", stage=None,
                        error=f"Lỗi máy xử lý: {type(exc).__name__}. Hãy thử tải lại sau.")
            last_beat = 0.0
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 - mất kết nối Supabase, v.v.: chờ rồi kết nối lại
            log.exception("Lỗi vòng lặp, thử lại sau 30 giây")
            try:
                if cloud is not None:
                    cloud.close()
            except Exception:  # noqa: BLE001
                pass
            cloud = None
            time.sleep(30)


if __name__ == "__main__":
    main()
