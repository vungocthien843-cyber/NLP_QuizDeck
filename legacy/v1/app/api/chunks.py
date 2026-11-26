"""Trả ảnh slide nguồn để hiển thị khi xem lại và khi bấm trích dẫn."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk

router = APIRouter(prefix="/chunks", tags=["chunks"])


@router.get("/{chunk_id}/image")
def get_chunk_image(chunk_id: int, db: Session = Depends(get_db)) -> FileResponse:
    chunk = db.get(Chunk, chunk_id)
    if not chunk or not chunk.image_path or not Path(chunk.image_path).is_file():
        raise HTTPException(404, "Không có ảnh cho chunk này")
    return FileResponse(chunk.image_path, media_type="image/png")
