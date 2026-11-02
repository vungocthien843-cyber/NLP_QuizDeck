"""Tạo đề bằng cách lấy mẫu từ ngân hàng câu hỏi (mục 8). Không gọi LLM."""
import random
from collections import defaultdict

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.generation.common import allocate
from app.models import Document, Question, Quiz, QuizQuestion
from app.retrieval.hybrid import scope_filter_sql
from app.schemas import BloomLevel, Scope


class EmptyBankError(ValueError):
    pass


def _candidates(db: Session, scope: Scope) -> list[Question]:
    stmt = (
        select(Question)
        .join(Document, Document.id == Question.document_id)
        .where(Question.status == "accepted", Document.is_active)
    )
    if scope.document_ids:
        stmt = stmt.where(Question.document_id.in_(scope.document_ids))
    if scope.session_nos:
        stmt = stmt.where(Question.session_no.in_(scope.session_nos))
    if scope.slide_from or scope.slide_to or scope.chapter_nos:
        where, params = scope_filter_sql(scope)
        chunk_ids = list(db.scalars(text(f"SELECT c.id FROM chunks c WHERE {where}"), params))
        if not chunk_ids:
            return []
        stmt = stmt.where(Question.source_chunk_ids.overlap(chunk_ids))
    return list(db.scalars(stmt))


def _round_robin(questions: list[Question], n: int, rng: random.Random) -> list[Question]:
    """Xoay vòng theo chunk nguồn chính để phủ đều nội dung; trong mỗi nhóm ưu tiên times_used thấp."""
    groups: dict[int, list[Question]] = defaultdict(list)
    for q in questions:
        groups[q.source_chunk_ids[0]].append(q)
    for g in groups.values():
        rng.shuffle(g)
        g.sort(key=lambda q: q.times_used)
    order = list(groups)
    rng.shuffle(order)
    picked: list[Question] = []
    while len(picked) < n and any(groups.values()):
        for key in order:
            if groups[key] and len(picked) < n:
                picked.append(groups[key].pop(0))
    return picked


def _pick_by_bloom(candidates: list[Question], n: int, mix: dict, rng: random.Random) -> list[Question]:
    """Chia theo Bloom → xoay vòng theo slide nguồn. Thiếu câu ở một mức thì bù từ mức khác."""
    by_level: dict[str, list[Question]] = defaultdict(list)
    for q in candidates:
        by_level[q.bloom_level or "remember"].append(q)
    picked: list[Question] = []
    for level, count in allocate(n, mix).items():
        picked += _round_robin(by_level.get(level, []), count, rng)
    if len(picked) < n:
        chosen = {q.id for q in picked}
        picked += _round_robin([q for q in candidates if q.id not in chosen], n - len(picked), rng)
    return picked


def create_quiz(db: Session, scope: Scope, n: int, bloom_mix: dict[BloomLevel, float] | None) -> Quiz:
    """Đề nhiều bài: chia số câu cho từng bài theo tỉ lệ số câu hỏi bài đó đang có, rồi trong mỗi bài
    chia theo Bloom. Tổng vẫn thiếu thì tạo đề với số câu hiện có (QuizOut báo num_questions < n)."""
    rng = random.Random()
    mix = bloom_mix or get_config().bank.bloom_mix
    candidates = _candidates(db, scope)
    if not candidates:
        raise EmptyBankError("Ngân hàng chưa có câu hỏi nào trong phạm vi đã chọn")

    by_doc: dict[int, list[Question]] = defaultdict(list)
    for q in candidates:
        by_doc[q.document_id].append(q)
    if len(by_doc) == 1:
        picked = _pick_by_bloom(candidates, n, mix, rng)
    else:
        quota = allocate(min(n, len(candidates)), {str(d): len(qs) for d, qs in by_doc.items()})
        picked = []
        for d, qs in by_doc.items():
            picked += _pick_by_bloom(qs, min(quota[str(d)], len(qs)), mix, rng)
        if len(picked) < n:
            chosen = {q.id for q in picked}
            picked += _round_robin([q for q in candidates if q.id not in chosen], n - len(picked), rng)
    rng.shuffle(picked)

    quiz = Quiz(scope=scope.model_dump(), num_questions=n, bloom_mix=mix)
    db.add(quiz)
    db.flush()
    db.add_all(QuizQuestion(quiz_id=quiz.id, question_id=q.id, position=i) for i, q in enumerate(picked, start=1))
    db.execute(update(Question).where(Question.id.in_([q.id for q in picked]))
               .values(times_used=Question.times_used + 1))
    db.commit()
    return quiz
