"""Gọi thẳng hàm retrieve, dùng để debug và chạy đánh giá (mục 6)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.access import restrict_scope
from app.auth.deps import require_user
from app.db import get_db
from app.retrieval.hybrid import retrieve
from app.models import User
from app.schemas import RetrievedChunk, SearchIn

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(require_user)])


@router.post("", response_model=list[RetrievedChunk])
def search(body: SearchIn, db: Session = Depends(get_db),
           user: User | None = Depends(require_user)) -> list[RetrievedChunk]:
    return retrieve(db, body.query, restrict_scope(db, user, body.scope), k=body.k, rerank=body.rerank, mode=body.mode)
