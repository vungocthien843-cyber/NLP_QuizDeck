"""Client gọi backend FastAPI. UI không truy cập DB trực tiếp."""
import json
import os
from urllib.parse import urlencode
from collections.abc import Iterator

import httpx
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
# Địa chỉ API mà TRÌNH DUYỆT truy cập được (ảnh slide tải thẳng từ trình duyệt). Trong Docker, API_BASE_URL là
# http://api:8000 (chỉ dùng được giữa các container) nên cần đặt PUBLIC_API_URL=http://localhost:8000.
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", API_BASE_URL).rstrip("/")

_client = httpx.Client(base_url=API_BASE_URL, timeout=60)


class ApiError(Exception):
    """Lỗi từ backend, mang nội dung `detail` để hiện cho người dùng."""


def _json(resp: httpx.Response):
    if resp.is_error:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise ApiError(f"{detail} (HTTP {resp.status_code})")
    return resp.json()


def safe(fn, *args, **kwargs):
    """Gọi API; lỗi thì hiện st.error và dừng trang thay vì in traceback."""
    import streamlit as st

    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        st.error(str(exc))
    except httpx.HTTPError:
        st.error(f"Không kết nối được backend tại {API_BASE_URL}. Kiểm tra container api đang chạy.")
    st.stop()


def upload_document(filename: str, content: bytes) -> dict:
    return _json(_client.post("/documents", files={"file": (filename, content)}))




def delete_document(document_id: int) -> None:
    resp = _client.delete(f"/documents/{document_id}")
    if resp.is_error:
        _json(resp)       # ném ApiError kèm detail


def list_documents() -> list[dict]:
    return _json(_client.get("/documents"))


def list_slides(document_id: int) -> dict:
    return _json(_client.get(f"/documents/{document_id}/slides"))


def slide_url(document_id: int, slide_no: int, highlight: str | None = None) -> str:
    """URL ảnh slide cho trình duyệt; `highlight` là đoạn văn cần tô vàng."""
    url = f"{PUBLIC_API_URL}/documents/{document_id}/slides/{slide_no}/image"
    return f"{url}?{urlencode({'highlight': highlight})}" if highlight else url








def create_quiz(scope: dict, n: int, bloom_mix: dict | None = None) -> dict:
    return _json(_client.post("/quizzes", json={"scope": scope, "n": n, "bloom_mix": bloom_mix}))




def submit_attempt(quiz_id: int, answers: dict[int, str], user_name: str | None = None) -> dict:
    return _json(_client.post("/attempts", json={"quiz_id": quiz_id, "answers": answers, "user_name": user_name}))


def get_review(attempt_id: int) -> dict:
    return _json(_client.get(f"/attempts/{attempt_id}/review"))




def chat_stream(message: str, conversation_id: int | None = None, attempt_id: int | None = None,
                question_id: int | None = None) -> tuple[int, Iterator[dict]]:
    """Trả (conversation_id, iterator các sự kiện NDJSON).
    question_id / attempt_id: câu trắc nghiệm đính kèm riêng tin nhắn này."""
    body = {"message": message, "conversation_id": conversation_id,
            "attempt_id": attempt_id, "question_id": question_id}
    req = _client.build_request("POST", "/chat", json=body)
    resp = _client.send(req, stream=True)
    if resp.is_error:
        resp.read()
        _json(resp)

    def events() -> Iterator[dict]:
        try:
            for line in resp.iter_lines():
                if line:
                    yield json.loads(line)
        finally:
            resp.close()

    return int(resp.headers["X-Conversation-Id"]), events()
