"""Đẩy nội dung bài giảng từ bản đầy đủ (Docker trên máy cá nhân) lên bản online (Supabase).

Chạy trên máy cá nhân, khi container db của Project_NLP đang chạy:
    pip install -r requirements-sync.txt
    python tools/sync_to_cloud.py --dry-run          # xem sẽ đẩy gì
    python tools/sync_to_cloud.py                    # đẩy mọi bài trong thư viện chung đã xử lý xong
    python tools/sync_to_cloud.py --doc 12 --doc 13  # chỉ đẩy vài bài
    python tools/sync_to_cloud.py --skip-images      # chỉ đẩy DB (ảnh đã lên rồi)

Biến môi trường (đặt trong file .env.sync ở thư mục gốc repo này, KHÔNG commit):
    LOCAL_DATABASE_URL   postgresql://<user>:<pass>@localhost:5432/<db>   (giá trị trong .env của Project_NLP)
    CLOUD_DATABASE_URL   chuỗi kết nối Supabase "Session pooler" hoặc "Direct" (cổng 5432)
    SUPABASE_URL, SUPABASE_SERVICE_KEY, STORAGE_BUCKET (mặc định slides)
    LOCAL_DATA_DIR       thư mục data/ của Project_NLP (mặc định D:/Project_NLP/data)

Nguyên tắc:
- Chỉ đẩy documents có is_shared = true, is_active = true, status = 'ready'. Slide riêng của sinh viên không lên.
- Chỉ đụng tới documents, chunks, questions, distractor_candidates, slide_assets. Không bao giờ ghi
  users, sessions, quizzes, attempts, responses, hồ sơ hiểu nhầm, hội thoại... của bản online.
- Upsert giữ nguyên id; không xoá dòng nào (bài làm online có thể đang trỏ tới câu hỏi cũ). Chạy lại nhiều lần
  cho kết quả như nhau.
- Một số cột do bản online tự quản lý thì không ghi đè khi dòng đã có (xem KEEP_ONLINE).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TABLES = ["documents", "chunks", "questions", "distractor_candidates"]
# Cột không ghi đè khi dòng đã có trên online (admin sửa online / số liệu từ bài làm thật của sinh viên)
KEEP_ONLINE = {
    "documents": {"is_active", "is_shared", "session_no", "pdf_key"},
    "chunks": {"is_active"},
    "questions": {"difficulty_elo", "times_used"},
    "distractor_candidates": set(),
}
# Cột không đẩy lên: sparse của bge-m3 (bản online tìm sparse bằng tsvector) → để NULL cho nhẹ DB
SKIP_COLUMNS = {"chunks": {"sparse"}, "questions": {"stem_embedding"}}   # stem_embedding chỉ dùng chống trùng khi sinh
BATCH = {"documents": 100, "chunks": 100, "questions": 200, "distractor_candidates": 500}


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        sys.exit(f"Thiếu biến môi trường {name} (đặt trong .env.sync)")
    return v


def dsn(name: str) -> str:
    """Chuỗi kết nối cho psycopg. Bỏ phần driver kiểu SQLAlchemy ("postgresql+psycopg://") nếu bạn chép nguyên
    DATABASE_URL của Docker, vì psycopg chỉ hiểu "postgresql://"."""
    v = env(name).strip().strip('"').strip("'")
    scheme, sep, rest = v.partition("://")
    return f"{scheme.split('+')[0]}{sep}{rest}"


def columns(conn: psycopg.Connection, table: str) -> list[str]:
    """Cột thường (bỏ cột sinh tự động như chunks.tsv)."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
        "AND is_generated = 'NEVER' ORDER BY ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows]


def select_docs(local: psycopg.Connection, only: list[int] | None) -> list[int]:
    sql = ("SELECT id, filename FROM documents WHERE is_shared AND is_active AND status = 'ready'"
           + (" AND id = ANY(%s)" if only else "") + " ORDER BY id")
    rows = local.execute(sql, (only,) if only else ()).fetchall()
    for i, name in rows:
        print(f"  • [{i}] {name}")
    if only:
        missing = set(only) - {r[0] for r in rows}
        for i in sorted(missing):
            print(f"  ! bỏ qua [{i}]: không có, không thuộc thư viện chung, hoặc chưa xử lý xong")
    return [r[0] for r in rows]


def where_for(table: str) -> str:
    return {
        "documents": "id = ANY(%s)",
        "chunks": "document_id = ANY(%s)",
        "questions": "document_id = ANY(%s)",
        "distractor_candidates": "question_id IN (SELECT id FROM questions WHERE document_id = ANY(%s))",
    }[table]


def sync_table(local, cloud, table: str, doc_ids: list[int], dry: bool) -> int:
    cols = [c for c in columns(local, table) if c in set(columns(cloud, table))
            and c not in SKIP_COLUMNS.get(table, set())]
    col_list = ", ".join(cols)
    update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id" and c not in KEEP_ONLINE[table])
    # to_jsonb ở local → jsonb_populate_recordset ở cloud: Postgres tự chuyển kiểu (vector, mảng, jsonb, thời gian)
    rows = local.execute(f"SELECT to_jsonb(t) FROM (SELECT {col_list} FROM {table} WHERE {where_for(table)} "
                         f"ORDER BY id) t", (doc_ids,)).fetchall()
    data = [r[0] for r in rows]
    if table == "documents":
        for d in data:
            d["owner_user_id"] = None           # tài khoản bên online khác hẳn local
    print(f"  {table}: {len(data)} dòng")
    if dry or not data:
        return len(data)
    sql = (f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM jsonb_populate_recordset(NULL::{table}, %s::jsonb) "
           f"ON CONFLICT (id) DO UPDATE SET {update}")
    n = BATCH[table]
    for i in range(0, len(data), n):
        cloud.execute(sql, (json.dumps(data[i:i + n], ensure_ascii=False),))
    return len(data)


def fix_sequences(cloud) -> None:
    for t in TABLES:
        cloud.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), GREATEST((SELECT COALESCE(MAX(id), 0) "
                      f"FROM {t}), 1))")


# ---------------------------------------------------------------- ảnh slide + PDF

def png_size(p: Path) -> tuple[int | None, int | None]:
    head = p.read_bytes()[:24]
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def local_file(data_dir: Path, container_path: str) -> Path:
    """file_path trong DB local là đường dẫn trong container (/app/data/...) → đổi sang thư mục data/ trên máy."""
    p = container_path.replace("\\", "/")
    for prefix in ("/app/data/", "data/"):
        if p.startswith(prefix):
            return data_dir / p[len(prefix):]
    return Path(container_path)


def find_pdf(data_dir: Path, doc_id: int, file_path: str) -> Path | None:
    src = local_file(data_dir, file_path)
    if src.suffix.lower() == ".pdf" and src.is_file():
        return src
    p = data_dir / "renders" / str(doc_id) / f"{Path(file_path).stem}.pdf"     # PPTX đã đổi sang PDF khi nạp
    return p if p.is_file() else None


class Uploader:
    def __init__(self) -> None:
        key = env("SUPABASE_SERVICE_KEY")
        self.base = env("SUPABASE_URL").rstrip("/") + "/storage/v1/object/" + os.environ.get("STORAGE_BUCKET", "slides")
        headers = {"apikey": key, "x-upsert": "true"}
        if not key.startswith("sb_"):               # khoá kiểu mới (sb_secret_...) không phải JWT: chỉ gửi qua apikey
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.Client(timeout=120, headers=headers)

    def put(self, key: str, path: Path, content_type: str) -> None:
        r = self.client.post(f"{self.base}/{quote(key)}", content=path.read_bytes(),
                             headers={"Content-Type": content_type})
        if r.status_code >= 400:
            raise RuntimeError(f"Upload {key} lỗi {r.status_code}: {r.text[:200]}")


def sync_assets(local, cloud, doc_ids: list[int], data_dir: Path, dry: bool, skip_upload: bool) -> None:
    up = None if dry or skip_upload else Uploader()
    for doc_id, file_path in local.execute("SELECT id, file_path FROM documents WHERE id = ANY(%s) ORDER BY id",
                                           (doc_ids,)).fetchall():
        pngs = sorted((data_dir / "renders" / str(doc_id)).glob("slide_*.png"))
        pdf = find_pdf(data_dir, doc_id, file_path)
        print(f"  [{doc_id}] {len(pngs)} ảnh slide, PDF: {pdf.name if pdf else 'KHÔNG THẤY (sẽ không tô vàng được)'}")
        if not pngs:
            print(f"  ! [{doc_id}] không thấy {data_dir / 'renders' / str(doc_id)}: kiểm tra LOCAL_DATA_DIR")
        if dry:
            continue
        rows = []
        for p in pngs:
            no = int(p.stem.split("_")[1])
            key = f"{doc_id}/{p.name}"
            if up:
                up.put(key, p, "image/png")
            w, h = png_size(p)
            rows.append((doc_id, no, w, h, key))
        cloud.cursor().executemany(                  # psycopg 3: executemany chỉ có ở cursor, không có ở Connection
            "INSERT INTO slide_assets (document_id, slide_no, width, height, png_key) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (document_id, slide_no) DO UPDATE SET width = EXCLUDED.width, height = EXCLUDED.height, "
            "png_key = EXCLUDED.png_key", rows)
        if pdf:
            key = f"{doc_id}/source.pdf"
            if up:
                up.put(key, pdf, "application/pdf")
            cloud.execute("UPDATE documents SET pdf_key = %s WHERE id = %s", (key, doc_id))
        cloud.commit()      # mỗi bài một lần commit: lỗi giữa chừng thì các bài trước vẫn giữ


def sync_documents(local, cloud, doc_ids: list[int], data_dir: Path, dry: bool = False,
                   skip_upload: bool = False) -> None:
    """Đẩy đúng các bài doc_ids (DB + ảnh slide + PDF). Dùng chung cho dòng lệnh và tools/worker.py."""
    print("Dữ liệu:")
    for t in TABLES:
        sync_table(local, cloud, t, doc_ids, dry)
    if not dry:
        fix_sequences(cloud)
        cloud.commit()
    print("Ảnh slide và PDF:")
    sync_assets(local, cloud, doc_ids, data_dir, dry, skip_upload)


def main() -> None:
    load_dotenv(ROOT / ".env.sync")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--doc", type=int, action="append", help="chỉ đẩy bài có id này (lặp lại được)")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in ra sẽ đẩy gì, không ghi gì")
    ap.add_argument("--skip-images", action="store_true", help="không upload ảnh/PDF (vẫn ghi slide_assets)")
    args = ap.parse_args()
    data_dir = Path(os.environ.get("LOCAL_DATA_DIR", "D:/Project_NLP/data"))

    with psycopg.connect(dsn("LOCAL_DATABASE_URL")) as local, \
            psycopg.connect(dsn("CLOUD_DATABASE_URL"), prepare_threshold=None) as cloud:
        if not cloud.execute("SELECT to_regclass('public.slide_assets')").fetchone()[0]:
            sys.exit("DB online chưa chạy migrations/100_lite.sql")
        print("Bài sẽ đẩy:")
        doc_ids = select_docs(local, args.doc)
        if not doc_ids:
            sys.exit("Không có bài nào để đẩy.")
        sync_documents(local, cloud, doc_ids, data_dir, args.dry_run, args.skip_images)
    print("Xong (dry-run, chưa ghi gì)." if args.dry_run else "Xong.")


if __name__ == "__main__":
    main()
