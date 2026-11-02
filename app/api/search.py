"""Gọi thẳng hàm retrieve, dùng để debug và chạy đánh giá (mục 6)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.retrieval.hybrid import retrieve
from app.schemas import RetrievedChunk, SearchIn

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=list[RetrievedChunk])
def search(body: SearchIn, db: Session = Depends(get_db)) -> list[RetrievedChunk]:
    return retrieve(db, body.query, body.scope, k=body.k, rerank=body.rerank, mode=body.mode)
