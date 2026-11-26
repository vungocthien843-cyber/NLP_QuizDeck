"""Trả ảnh slide nguồn để hiển thị khi xem lại và khi bấm trích dẫn."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.access import can_view
from app.auth.deps import require_user
from app.db import get_db
from app.models import Chunk, Document, User

router = APIRouter(prefix="/chunks", tags=["chunks"], dependencies=[Depends(require_user)])


@router.get("/{chunk_id}/image")
def get_chunk_image(chunk_id: int, db: Session = Depends(get_db),
                    user: User | None = Depends(require_user)) -> FileResponse:
    chunk = db.get(Chunk, chunk_id)
    if not chunk or not can_view(user, db.get(Document, chunk.document_id)) or not chunk.image_path or not Path(chunk.image_path).is_file():
        raise HTTPException(404, "Không có ảnh cho chunk này")
    return FileResponse(chunk.image_path, media_type="image/png")
