"""Điều phối Luồng 1 (mục 5): parse → VLM → chunk → embed → lưu → sinh ngân hàng câu hỏi."""
import asyncio
import logging

from app.db import SessionLocal
from app.generation.bank_builder import build_bank
from app.ingestion.chunker import build_chunks
from app.ingestion.image_filter import filter_images
from app.ingestion.lang_detect import detect_lang
from app.ingestion.slide_parser import parse_slides
from app.ingestion.vlm_caption import caption_slides
from app.models import Chunk, Document
from app.retrieval.embedder import get_embedder

log = logging.getLogger(__name__)


def _set_status(document_id: int, status: str, error: str | None = None) -> None:
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        doc.status, doc.error = status, error
        db.commit()


def run_pipeline(document_id: int) -> None:
    """Chạy trong BackgroundTasks (thread pool), nên tự mở session và event loop riêng."""
    try:
        with SessionLocal() as db:
            doc = db.get(Document, document_id)
            file_path, session_no = doc.file_path, doc.session_no

        _set_status(document_id, "parsing")
        pages = parse_slides(file_path, document_id)
        filter_images(pages)
        asyncio.run(caption_slides(pages))

        _set_status(document_id, "embedding")
        drafts = build_chunks(pages, session_no)
        for d in drafts:
            d.lang = detect_lang(d.embed_text)
        if not drafts:
            raise ValueError("Không trích được nội dung nào từ file (slide trống hoặc chỉ có ảnh mà VLM lỗi)")
        vectors = get_embedder().encode([d.embed_text for d in drafts])

        with SessionLocal() as db:
            db.add_all(
                Chunk(document_id=document_id, source_type="slide", embedding=v.dense, sparse=v.sparse, **d.to_row())
                for d, v in zip(drafts, vectors, strict=True)
            )
            db.commit()

        _set_status(document_id, "generating")
        warning = asyncio.run(build_bank(document_id))
        _set_status(document_id, "ready", warning)
    except Exception as exc:
        log.exception("Ingestion thất bại cho document %s", document_id)
        _set_status(document_id, "failed", str(exc)[:1000])
