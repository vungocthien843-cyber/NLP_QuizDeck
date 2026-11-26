"""Điểm vào FastAPI: gắn router, khởi động thì dọn job dở dang và nạp sẵn model embedding."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import update

from app.api import attempts, chat, chunks, documents, quizzes, search
from app.config import get_settings
from app.db import SessionLocal
from app.models import Document
from app.retrieval.embedder import get_embedder

STUCK_STATUSES = ("uploaded", "parsing", "embedding", "generating")


def reset_stuck_documents() -> None:
    """Job chạy bằng BackgroundTasks mất khi restart: đánh dấu failed để người dùng chạy lại."""
    with SessionLocal() as db:
        db.execute(
            update(Document)
            .where(Document.status.in_(STUCK_STATUSES))
            .values(status="failed", error="Tiến trình bị dừng do API khởi động lại")
        )
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.render_dir.mkdir(parents=True, exist_ok=True)
    reset_stuck_documents()
    get_embedder()  # nạp bge-m3 một lần (~2,3 GB)
    yield


app = FastAPI(title="RAG Quiz API", lifespan=lifespan)
for module in (documents, search, quizzes, attempts, chat, chunks):
    app.include_router(module.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
