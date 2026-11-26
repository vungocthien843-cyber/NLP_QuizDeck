"""API quản trị (chỉ email trong ADMIN_EMAILS): thống kê cả lớp, danh sách sinh viên, ngân hàng câu hỏi, xử lý lại bài lỗi."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_admin
from app.db import get_db
from app.ingestion.pipeline import run_pipeline
from app.api.users import attempt_summaries
from app.models import Attempt, Chunk, Conversation, Document, Question, QuizQuestion, Response, User
from app.schemas import AttemptSummary
from app.prompts import misconception_types

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

STEP_VI = {"source_ids": "Trích sai nguồn", "form": "Sai hình thức", "evidence": "Không có căn cứ trong slide",
           "duplicate": "Trùng câu đã có"}
RULE_VI = {
    "outside_context": "Dẫn nguồn ngoài ngữ cảnh", "seed_missing": "Không bám slide gốc",
    "banned_phrase": "Có phương án “tất cả đều đúng/sai”", "double_negation": "Phủ định kép",
    "context_reference": "Nhắc tới “ngữ cảnh/đoạn trên”", "correct_too_long": "Đáp án đúng dài lộ liễu",
    "answer_in_stem": "Câu hỏi lộ đáp án", "letter_reference": "Nhắc chữ cái A/B/C/D",
    "too_short": "Trích dẫn quá ngắn", "not_verbatim": "Trích dẫn không khớp slide", "duplicate": "Trùng ý câu đã có",
}


# ---------- Tổng quan cả lớp ----------
class DocStat(BaseModel):
    document_id: int
    filename: str
    n_answered: int
    accuracy: float | None


class DayStat(BaseModel):
    day: str
    n_attempts: int


class ClassStats(BaseModel):
    n_students: int
    n_active_7d: int
    n_attempts: int
    n_answered: int
    accuracy: float | None
    n_documents: int
    n_questions: int
    by_document: list[DocStat]
    by_error_type: dict[str, int]
    error_type_names: dict[str, str]
    attempts_by_day: list[DayStat]


@router.get("/stats", response_model=ClassStats)
def stats(db: Session = Depends(get_db)) -> ClassStats:
    now = datetime.now(timezone.utc)
    students = select(User.id).where(User.is_admin.is_(False))
    n_answered, n_correct = db.execute(
        select(func.count(), func.count().filter(Response.is_correct))
        .where(Response.chosen.is_not(None))).one()
    by_doc = db.execute(
        select(Document.id, Document.filename, func.count(Response.id), func.count().filter(Response.is_correct))
        .join(Question, Question.document_id == Document.id).join(Response, Response.question_id == Question.id)
        .where(Document.is_active, Response.chosen.is_not(None)).group_by(Document.id, Document.filename)
        .order_by(Document.session_no.nulls_last(), Document.id)).all()
    by_type = Counter(dict(db.execute(select(Response.error_type, func.count())
                                      .where(Response.is_correct.is_(False), Response.error_type.is_not(None))
                                      .group_by(Response.error_type)).all()))
    since = (now - timedelta(days=13)).date()
    per_day = dict(db.execute(select(func.date(Attempt.submitted_at), func.count())
                              .where(func.date(Attempt.submitted_at) >= since)
                              .group_by(func.date(Attempt.submitted_at))).all())
    return ClassStats(
        n_students=db.scalar(select(func.count()).select_from(students.subquery())) or 0,
        n_active_7d=db.scalar(select(func.count(func.distinct(Attempt.user_id)))
                              .where(Attempt.submitted_at >= now - timedelta(days=7))) or 0,
        n_attempts=db.scalar(select(func.count(Attempt.id))) or 0,
        n_answered=n_answered or 0,
        accuracy=(n_correct / n_answered) if n_answered else None,
        n_documents=db.scalar(select(func.count(Document.id)).where(Document.is_active)) or 0,
        n_questions=db.scalar(select(func.count(Question.id)).join(Document, Document.id == Question.document_id)
                              .where(Document.is_active, Question.status == "accepted")) or 0,
        by_document=[DocStat(document_id=i, filename=f, n_answered=n, accuracy=(c / n) if n else None)
                     for i, f, n, c in by_doc],
        by_error_type=dict(by_type.most_common()),
        error_type_names={k: v["ten"] for k, v in misconception_types().items()},
        attempts_by_day=[DayStat(day=str(since + timedelta(days=i)), n_attempts=per_day.get(since + timedelta(days=i), 0))
                         for i in range(14)],
    )


# ---------- Sinh viên ----------
class UserRow(BaseModel):
    user_id: int
    email: str | None
    name: str | None
    avatar_url: str | None
    is_admin: bool
    last_login_at: str | None
    n_attempts: int
    avg_score: float | None
    accuracy: float | None
    n_own_docs: int


@router.get("/users", response_model=list[UserRow])
def users(db: Session = Depends(get_db)) -> list[UserRow]:
    att = dict((u, (n, s)) for u, n, s in db.execute(
        select(Attempt.user_id, func.count(Attempt.id), func.avg(Attempt.score)).group_by(Attempt.user_id)).all())
    acc = dict((u, (n, c)) for u, n, c in db.execute(
        select(Response.user_id, func.count(), func.count().filter(Response.is_correct))
        .where(Response.chosen.is_not(None)).group_by(Response.user_id)).all())
    docs = dict(db.execute(select(Document.owner_user_id, func.count()).where(
        Document.is_active, Document.is_shared.is_(False)).group_by(Document.owner_user_id)).all())
    rows = []
    for u in db.scalars(select(User).order_by(User.last_login_at.desc().nulls_last(), User.id.desc())):
        n_att, avg = att.get(u.id, (0, None))
        n_ans, n_ok = acc.get(u.id, (0, 0))
        rows.append(UserRow(user_id=u.id, email=u.email, name=u.display_name, avatar_url=u.avatar_url,
                            is_admin=u.is_admin, last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
                            n_attempts=n_att, avg_score=float(avg) if avg is not None else None,
                            accuracy=(n_ok / n_ans) if n_ans else None, n_own_docs=docs.get(u.id, 0)))
    return rows


# ---------- Ngân hàng câu hỏi ----------
class BankQuestion(BaseModel):
    question_id: int
    stem: str
    options: dict[str, str]
    answer: str
    explanation: str | None
    bloom_level: str | None
    difficulty: str | None
    concept: str | None
    status: str
    reject_reason: str | None
    times_used: int
    n_answered: int
    accuracy: float | None
    slide_no: int | None
    error_types: dict[str, str | None]     # chữ cái phương án nhiễu → loại hiểu nhầm


def _reject_reason(v: dict | None) -> str | None:
    for step in ("source_ids", "form", "evidence", "duplicate"):
        r = (v or {}).get(step)
        if isinstance(r, dict) and r.get("passed") is False:
            rule = (r.get("details") or {}).get("rule") or r.get("reason")
            label = STEP_VI.get(step, step)
            return f"{label}: {RULE_VI[rule]}" if rule in RULE_VI and RULE_VI[rule] != label else label
    return None


@router.get("/documents/{document_id}/questions", response_model=list[BankQuestion])
def bank(document_id: int, status: str | None = None, db: Session = Depends(get_db)) -> list[BankQuestion]:
    if db.get(Document, document_id) is None:
        raise HTTPException(404, "Không tìm thấy tài liệu")
    q = select(Question).where(Question.document_id == document_id)
    if status in ("accepted", "rejected"):
        q = q.where(Question.status == status)
    questions = db.scalars(q.order_by(Question.status, Question.id)).all()
    stats = dict((qid, (n, c)) for qid, n, c in db.execute(
        select(Response.question_id, func.count(), func.count().filter(Response.is_correct))
        .where(Response.question_id.in_([x.id for x in questions]), Response.chosen.is_not(None))
        .group_by(Response.question_id)).all()) if questions else {}
    first_chunk = {x.id: (x.source_chunk_ids or [None])[0] for x in questions}
    slides = dict(db.execute(select(Chunk.id, Chunk.slide_no).where(
        Chunk.id.in_([c for c in first_chunk.values() if c])) ).all()) if questions else {}
    out = []
    for x in questions:
        n, c = stats.get(x.id, (0, 0))
        meta = x.option_meta or {}
        out.append(BankQuestion(
            question_id=x.id, stem=x.stem, options=x.options, answer=x.answer, explanation=x.explanation,
            bloom_level=x.bloom_level, difficulty=x.difficulty_est, concept=x.concept, status=x.status,
            reject_reason=_reject_reason(x.validation) if x.status == "rejected" else None,
            times_used=x.times_used or 0, n_answered=n, accuracy=(c / n) if n else None,
            slide_no=(x.validation or {}).get("evidence_slide_no") or slides.get(first_chunk[x.id]),
            error_types={k: (v or {}).get("error_type") for k, v in meta.items() if (v or {}).get("role") != "key"},
        ))
    return out


@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess(document_id: int, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    """Chạy lại toàn bộ xử lý cho bài bị lỗi (xóa chunk và câu hỏi cũ của lần chạy hỏng)."""
    doc = db.get(Document, document_id)
    if doc is None or not doc.is_active:
        raise HTTPException(404, "Không tìm thấy tài liệu")
    if doc.status != "failed":
        raise HTTPException(409, "Chỉ xử lý lại được bài đang ở trạng thái lỗi")
    qids = select(Question.id).where(Question.document_id == document_id)
    used = (db.scalar(select(func.count(Response.id)).where(Response.question_id.in_(qids))) or 0) + \
           (db.scalar(select(func.count()).select_from(QuizQuestion).where(QuizQuestion.question_id.in_(qids))) or 0)
    if used:
        raise HTTPException(409, "Bài đã có người làm, không xử lý lại được. Hãy tải lên bài mới.")
    db.query(Conversation).filter(Conversation.question_id.in_(qids)).update({"question_id": None},
                                                                            synchronize_session=False)
    db.execute(delete(Question).where(Question.document_id == document_id))
    db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    doc.status, doc.error = "uploaded", None
    db.commit()
    background.add_task(run_pipeline, document_id)
    return {"status": "uploaded"}


@router.get("/users/{user_id}/attempts", response_model=list[AttemptSummary])
def user_attempts(user_id: int, db: Session = Depends(get_db)) -> list[AttemptSummary]:
    if db.get(User, user_id) is None:
        raise HTTPException(404, "Không tìm thấy người dùng")
    return attempt_summaries(db, user_id)
