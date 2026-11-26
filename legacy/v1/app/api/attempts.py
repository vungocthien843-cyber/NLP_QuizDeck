"""Nộp bài, chấm điểm, xem lại kèm nguồn (mục 8). Không gọi LLM."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import slides
from app.db import get_db
from app.models import Attempt, Chunk, Document, Question, Quiz, QuizQuestion
from app.schemas import AttemptIn, AttemptOut, ReviewItem, ReviewOut, SourceOut

router = APIRouter(prefix="/attempts", tags=["attempts"])


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
def submit_attempt(body: AttemptIn, db: Session = Depends(get_db)) -> AttemptOut:
    if not db.get(Quiz, body.quiz_id):
        raise HTTPException(404, "Không tìm thấy đề")
    questions = _quiz_questions(db, body.quiz_id)
    if set(body.answers) != {q.id for q in questions}:
        raise HTTPException(400, "Phải trả lời đủ tất cả câu hỏi của đề")

    num_correct = sum(body.answers[q.id] == q.answer for q in questions)
    score_10 = round(10 * num_correct / len(questions), 2)
    attempt = Attempt(
        quiz_id=body.quiz_id, user_name=body.user_name,
        answers={str(k): v for k, v in body.answers.items()}, score=score_10,
    )
    db.add(attempt)
    db.commit()
    return AttemptOut(
        attempt_id=attempt.id, num_correct=num_correct, num_questions=len(questions), score_10=score_10
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
    doc = docs.get(chunk.document_id)
    slide = slides.locate(doc, text, list(range(first, last + 1))) if doc else None
    return text, chunk.document_id, slide or first


@router.get("/{attempt_id}/review", response_model=ReviewOut)
def review_attempt(attempt_id: int, db: Session = Depends(get_db)) -> ReviewOut:
    attempt = db.get(Attempt, attempt_id)
    if not attempt:
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
        ))
    return ReviewOut(attempt_id=attempt.id, score_10=attempt.score or 0.0, items=items)
