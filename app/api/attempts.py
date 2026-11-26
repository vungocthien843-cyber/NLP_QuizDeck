"""Nộp bài, chấm điểm, xem lại kèm nguồn (mục 8). Không gọi LLM."""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import slides
from app.auth.access import can_view_quiz
from app.auth.deps import can_view_user, effective_user_id, require_user
from app.db import get_db
from app.learner.profile import describe, update_after_attempt
from app.models import Attempt, Chunk, Document, Question, Quiz, QuizQuestion, Response, User
from app.schemas import AttemptIn, AttemptOut, ReviewItem, ReviewOut, SourceOut

router = APIRouter(prefix="/attempts", tags=["attempts"])
log = logging.getLogger(__name__)


def _quiz_questions(db: Session, quiz_id: int) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.position)
        )
    )


@router.post("", response_model=AttemptOut)
def submit_attempt(body: AttemptIn, db: Session = Depends(get_db),
                   user: User | None = Depends(require_user)) -> AttemptOut:
    body.user_id = effective_user_id(user, body.user_id)
    if not can_view_quiz(user, db.get(Quiz, body.quiz_id)):
        raise HTTPException(404, "Không tìm thấy đề")
    questions = _quiz_questions(db, body.quiz_id)
    qids = {q.id for q in questions}
    if not set(body.answers) <= qids:
        raise HTTPException(400, "Có câu trả lời không thuộc đề này")
    if set(body.answers) != qids and not body.allow_unanswered:
        raise HTTPException(400, "Phải trả lời đủ tất cả câu hỏi của đề")

    if body.user_id is not None and db.get(User, body.user_id) is None:
        raise HTTPException(404, "Không tìm thấy người học")

    num_correct = sum(body.answers.get(q.id) == q.answer for q in questions)
    score_10 = round(10 * num_correct / len(questions), 2)
    quiz = db.get(Quiz, body.quiz_id)
    attempt = Attempt(
        quiz_id=body.quiz_id, user_name=body.user_name,
        answers={str(k): v for k, v in body.answers.items()}, score=score_10,
        user_id=body.user_id, mode=quiz.mode or "normal",
    )
    db.add(attempt)
    db.flush()
    responses = [_response(attempt, q, body.answers.get(q.id), (body.times_ms or {}).get(q.id)) for q in questions]
    db.add_all(responses)
    update_after_attempt(db, body.user_id, responses)
    db.commit()
    return AttemptOut(
        attempt_id=attempt.id, num_correct=num_correct, num_questions=len(questions), score_10=score_10
    )


def _response(attempt: Attempt, q: Question, chosen: str | None, time_ms: int | None) -> Response:
    """v3 (C3): một dòng cho mỗi câu; phương án sai đã chọn mang loại hiểu nhầm lấy từ option_meta."""
    meta = ((q.option_meta or {}).get(chosen) or {}) if chosen else {}
    correct = chosen == q.answer
    return Response(
        attempt_id=attempt.id, user_id=attempt.user_id, question_id=q.id, chosen=chosen, is_correct=correct,
        score=1.0 if correct else 0.0, candidate_id=None if correct else meta.get("candidate_id"),
        error_type=None if correct else meta.get("error_type"),
        concept=q.concept or (q.validation or {}).get("key_point"), time_ms=time_ms,
    )


def _evidence(q: Question, chunks: dict[int, Chunk], docs: dict[int, Document]) -> tuple[str | None, int | None, int | None]:
    """Câu trích nguyên văn (lưu trong validation khi sinh câu hỏi) và slide chứa nó.
    Câu sinh trước khi có bước trích dẫn thì không có evidence: trả None, UI dùng chunk nguồn."""
    v = q.validation or {}
    text = v.get("evidence_text")
    if not isinstance(text, str) or not text.strip():
        return None, None, None
    step = v.get("evidence") if isinstance(v.get("evidence"), dict) else {}
    chunk = chunks.get((step.get("details") or {}).get("chunk_id")) or next(
        (chunks[c] for c in q.source_chunk_ids if c in chunks), None)
    if not chunk:
        return text, None, None
    first, last = chunk.slide_no or 1, chunk.slide_end or chunk.slide_no or 1
    cached = v.get("evidence_slide_no")
    if isinstance(cached, int):                 # đã dò từ trước: không mở PDF (đọc PDF qua bind mount rất chậm)
        return text, chunk.document_id, cached
    doc = docs.get(chunk.document_id)
    slide = (slides.locate(doc, text, list(range(first, last + 1))) if doc else None) or first
    q.validation = {**v, "evidence_slide_no": slide}   # lưu lại để lần sau và sau khi khởi động lại vẫn nhanh
    return text, chunk.document_id, slide


@router.get("/{attempt_id}/review", response_model=ReviewOut)
def review_attempt(attempt_id: int, db: Session = Depends(get_db),
                   user: User | None = Depends(require_user)) -> ReviewOut:
    t0 = time.perf_counter()
    attempt = db.get(Attempt, attempt_id)
    if not attempt or not can_view_user(user, attempt.user_id):
        raise HTTPException(404, "Không tìm thấy bài làm")
    questions = _quiz_questions(db, attempt.quiz_id)

    chunk_ids = {cid for q in questions for cid in q.source_chunk_ids}
    for q in questions:
        ev = (q.validation or {}).get("evidence")
        if isinstance(ev, dict) and (ev.get("details") or {}).get("chunk_id"):
            chunk_ids.add(ev["details"]["chunk_id"])
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))}
    docs = {d.id: d for d in db.scalars(select(Document).where(
        Document.id.in_({c.document_id for c in chunks.values()})))}

    items = []
    for q in questions:
        chosen = attempt.answers.get(str(q.id))
        sources = [
            SourceOut(
                chunk_id=c.id, document_id=c.document_id, session_no=c.session_no, slide_no=c.slide_no,
                slide_end=c.slide_end, title=c.title, raw_text=c.raw_text,
                image_url=f"/chunks/{c.id}/image" if c.image_path else None,
            )
            for cid in q.source_chunk_ids
            if (c := chunks.get(cid))
        ]
        evidence, ev_doc, ev_slide = _evidence(q, chunks, docs)
        items.append(ReviewItem(
            question_id=q.id, stem=q.stem, options=q.options, chosen=chosen, answer=q.answer,
            is_correct=chosen == q.answer, rationales=q.rationales, explanation=q.explanation,
            bloom_level=q.bloom_level, sources=sources,
            evidence=evidence, evidence_document_id=ev_doc, evidence_slide_no=ev_slide,
            misconception=None if chosen == q.answer else describe(((q.option_meta or {}).get(chosen) or {})
                                                                    .get("error_type")),
        ))
    if db.dirty:                                # có câu vừa được lưu evidence_slide_no
        db.commit()
    log.info("review attempt %s: %d câu, %.2f s", attempt_id, len(items), time.perf_counter() - t0)
    return ReviewOut(attempt_id=attempt.id, score_10=attempt.score or 0.0, items=items)
