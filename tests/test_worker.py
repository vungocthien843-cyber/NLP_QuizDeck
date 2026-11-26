"""Máy worker (tools/worker.py): kiểm tra PDF, nhận việc từ hàng đợi, trả việc làm dở, đẩy sequence.
"Supabase" được giả bằng một schema tạm trong DB test (xoá sau mỗi test). Không gọi LLM, không gọi mạng.

Chạy trong container (tools/ đã mount sẵn ở service worker; với api thì chép vào):
    docker compose cp tools api:/app/tools && docker compose cp tests api:/app/tests
    docker compose exec api sh -c "cd /app && TEST_DATABASE_URL=\\$DATABASE_URL python -m pytest -q tests/test_worker.py"
"""
import os

import fitz
import psycopg
import pytest

from tools import worker

needs_db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")
SCHEMA = "__test_cloud"


def _dsn() -> str:
    scheme, sep, rest = os.environ["TEST_DATABASE_URL"].partition("://")
    return f"{scheme.split('+')[0]}{sep}{rest}"


def make_pdf(path, pages: int) -> None:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Trang {i + 1}")
    doc.save(path)


def test_check_pdf(tmp_path, monkeypatch):
    ok = tmp_path / "ok.pdf"
    make_pdf(ok, 3)
    worker.check_pdf(ok)

    monkeypatch.setattr(worker, "MAX_PAGES", 2)
    with pytest.raises(worker.JobFailed, match="vượt giới hạn 2 trang"):
        worker.check_pdf(ok)

    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"PK\x03\x04 day la file zip")
    with pytest.raises(worker.JobFailed, match="không phải PDF"):
        worker.check_pdf(fake)


@pytest.fixture
def cloud():
    """Kết nối giả làm Supabase: bảng upload_jobs nằm trong schema tạm, các bảng khác dùng chung DB test."""
    conn = psycopg.connect(_dsn(), autocommit=True)
    conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCHEMA}")
    conn.execute(f"SET search_path TO {SCHEMA}, public")
    conn.execute(f"""
        CREATE TABLE {SCHEMA}.upload_jobs (
          id SERIAL PRIMARY KEY, user_id INT, filename TEXT NOT NULL, storage_key TEXT NOT NULL,
          size_bytes BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_file', stage TEXT, error TEXT,
          document_id INT, worker_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          claimed_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
        CREATE TABLE {SCHEMA}.worker_heartbeats (worker_id TEXT PRIMARY KEY, seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          device TEXT);""")
    yield conn
    conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.close()


def _add_job(cloud, name: str, status: str = "pending", worker_id: str | None = None) -> int:
    return cloud.execute("INSERT INTO upload_jobs (filename, storage_key, size_bytes, status, worker_id) "
                         "VALUES (%s, %s, 1, %s, %s) RETURNING id", (name, f"uploads/{name}", status, worker_id)
                         ).fetchone()[0]


@needs_db
def test_claim_oldest_pending_once(cloud, monkeypatch):
    monkeypatch.setattr(worker, "WORKER_ID", "__test_w1")
    _add_job(cloud, "cho.pdf", status="awaiting_file")      # chưa tải xong file: không được nhận
    first = _add_job(cloud, "a.pdf")
    second = _add_job(cloud, "b.pdf")

    job = worker.claim(cloud)
    assert job[0] == first and job[2] == "a.pdf"
    assert worker.claim(cloud)[0] == second
    assert worker.claim(cloud) is None
    status, wid = cloud.execute("SELECT status, worker_id FROM upload_jobs WHERE id = %s", (first,)).fetchone()
    assert (status, wid) == ("processing", "__test_w1")

    worker.set_job(cloud, first, status="ready", stage=None)
    assert cloud.execute("SELECT finished_at IS NOT NULL FROM upload_jobs WHERE id = %s", (first,)).fetchone()[0]


@needs_db
def test_requeue_only_own_jobs(cloud, monkeypatch):
    monkeypatch.setattr(worker, "WORKER_ID", "__test_w1")
    mine = _add_job(cloud, "cua_toi.pdf", status="processing", worker_id="__test_w1")
    other = _add_job(cloud, "may_khac.pdf", status="processing", worker_id="__test_w2")
    worker.requeue_own(cloud)
    rows = dict(cloud.execute("SELECT id, status FROM upload_jobs").fetchall())
    assert rows[mine] == "pending" and rows[other] == "processing"

    worker.heartbeat(cloud, "cpu")
    worker.heartbeat(cloud, "cuda (test)")
    assert cloud.execute("SELECT device FROM worker_heartbeats WHERE worker_id = '__test_w1'").fetchone()[0] == "cuda (test)"


@needs_db
def test_bump_local_sequences_never_below_existing_ids(cloud):
    with psycopg.connect(_dsn()) as local:
        worker.bump_local_sequences(local, cloud)
        for t in worker.TABLES:
            seq = local.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,)).fetchone()[0]
            last = local.execute(f"SELECT last_value FROM {seq}").fetchone()[0]
            top = local.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0]
            assert last >= top, t
