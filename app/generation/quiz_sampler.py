"""Tạo đề bằng cách lấy mẫu từ ngân hàng câu hỏi (mục 8). Không gọi LLM."""
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.generation.common import allocate
from app.models import Document, Question, Quiz, QuizQuestion, Response
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


@dataclass
class QuizResult:
    quiz: Quiz
    notice: str | None = None
    reasons: dict[int, dict] = field(default_factory=dict)


# Thứ tự bù khi không đủ câu đúng mức khó: mức gần nhất trước
_FALLBACK = {"easy": ["medium", "hard"], "medium": ["easy", "hard"], "hard": ["medium", "easy"]}


def filter_difficulty(candidates: list[Question], n: int, difficulty: str | None) -> tuple[list[Question], str | None]:
    """v3 (D5): giữ câu đúng mức; thiếu thì bù từ mức gần nhất và báo lại. Câu chưa có difficulty_est coi là medium."""
    if not difficulty:
        return candidates, None
    level = {q.id: (q.difficulty_est or "medium") for q in candidates}
    out = [q for q in candidates if level[q.id] == difficulty]
    if len(out) >= n:
        return out, None
    have = len(out)
    for lv in _FALLBACK[difficulty]:
        out += [q for q in candidates if level[q.id] == lv][: n - len(out)]
        if len(out) >= n:
            break
    names = {"easy": "Dễ", "medium": "Trung bình", "hard": "Khó"}
    return out, f"Chỉ có {have} câu mức {names[difficulty]} trong phạm vi; đã bù bằng câu mức gần nhất."


def weak_chunks(db: Session, user_id: int, weak_types: dict[str, set[str]]) -> dict[int, set[str]]:
    """Slide nguồn (chunk hạt giống) của các câu người học đã chọn sai vì một hiểu nhầm đang yếu → các loại lỗi đó."""
    if not weak_types:
        return {}
    rows = db.execute(select(Response.concept, Response.error_type, Question.source_chunk_ids)
                      .join(Question, Question.id == Response.question_id)
                      .where(Response.user_id == user_id, Response.is_correct.is_(False),
                             Response.concept.in_(list(weak_types)))).all()
    out: dict[int, set[str]] = defaultdict(set)
    for concept, err, chunks in rows:
        if chunks and err in weak_types.get(concept, ()):
            out[chunks[0]].add(err)
    return dict(out)


def weakness_priority(db: Session, user_id: int, candidates: list[Question]) -> tuple[dict[int, float], dict[int, dict]]:
    """v3 (D6): điểm ưu tiên của từng câu cho người học:
      +2   câu kiểm tra một ý kiến thức người học đang yếu (top_weaknesses): cùng chuỗi concept, HOẶC cùng slide nguồn
           với câu người học đã chọn sai vì hiểu nhầm đó (concept là key_point do LLM viết cho từng câu nên hai câu
           khác nhau về cùng một ý hiếm khi trùng chuỗi; trước 15/11 chỉ so chuỗi nên gần như chỉ gặp lại đúng câu cũ)
      +1   câu có đáp án nhiễu cùng loại hiểu nhầm người học hay mắc ở ý đó (cơ hội kiểm tra lại đúng hiểu nhầm)
      −1   đã làm câu này trong 24 giờ qua
      −0,5 đã trả lời đúng câu này trong 7 ngày qua"""
    from app.learner.profile import top_weaknesses

    weak = top_weaknesses(db, user_id, k=get_config().learner.weakness_top_k)
    if not weak:
        return {}, {}
    weak_types = defaultdict(set)
    for w in weak:
        weak_types[w["concept"]].add(w["error_type"])
    chunk_types = weak_chunks(db, user_id, weak_types)
    now = datetime.now(timezone.utc)
    recent = db.execute(select(Response.question_id, Response.is_correct, Response.created_at).where(
        Response.user_id == user_id, Response.created_at >= now - timedelta(days=7))).all()
    seen_24h = {qid for qid, _, t in recent if t >= now - timedelta(hours=24)}
    correct_7d = {qid for qid, ok, _ in recent if ok}
    prio, reasons = {}, {}
    for q in candidates:
        concept = q.concept or (q.validation or {}).get("key_point")
        seed = q.source_chunk_ids[0] if q.source_chunk_ids else None
        p, why = 0.0, {}
        if concept in weak_types or seed in chunk_types:
            p += 2
            why["weak_concept"] = concept if concept in weak_types else f"slide nguồn {seed}"
            types = {m.get("error_type") for m in (q.option_meta or {}).values() if m.get("role") == "distractor"}
            hit = types & (weak_types.get(concept, set()) | chunk_types.get(seed, set()))
            if hit:
                p += 1
                why["error_types"] = sorted(hit)
        if q.id in seen_24h:
            p -= 1
        if q.id in correct_7d:
            p -= 0.5
        prio[q.id] = p
        if p > 0:
            reasons[q.id] = {**why, "priority": p}
    return prio, reasons


def pick_weakness(candidates: list[Question], prio: dict[int, float], n: int, rng: random.Random) -> list[Question]:
    """Lấy câu ưu tiên cao trước, mỗi slide nguồn tối đa 2 câu ở lượt đầu để không dồn vào một slide."""
    ranked = sorted(candidates, key=lambda q: (-prio.get(q.id, 0), q.times_used, rng.random()))
    positive = [q for q in ranked if prio.get(q.id, 0) > 0]
    picked, per_chunk = [], defaultdict(int)
    for q in positive:
        if len(picked) >= n:
            break
        if per_chunk[q.source_chunk_ids[0]] < 2:
            picked.append(q)
            per_chunk[q.source_chunk_ids[0]] += 1
    chosen = {q.id for q in picked}
    for q in positive:                        # lượt hai: bỏ giới hạn mỗi slide
        if len(picked) >= n:
            break
        if q.id not in chosen:
            picked.append(q)
            chosen.add(q.id)
    if len(picked) < n:                        # thiếu thì bù bằng cách lấy mẫu thường
        picked += _round_robin([q for q in candidates if q.id not in chosen], n - len(picked), rng)
    return picked


def create_quiz(db: Session, scope: Scope, n: int, bloom_mix: dict[BloomLevel, float] | None,
                difficulty: str | None = None, mode: str = "normal", user_id: int | None = None) -> QuizResult:
    """Đề nhiều bài: chia số câu cho từng bài theo tỉ lệ số câu hỏi bài đó đang có, rồi trong mỗi bài
    chia theo Bloom. Tổng vẫn thiếu thì tạo đề với số câu hiện có (QuizOut báo num_questions < n).
    v3: difficulty lọc theo mức khó ước lượng; mode="weakness" ưu tiên câu nhắm vào hiểu nhầm của người học."""
    rng = random.Random()
    mix = bloom_mix or get_config().bank.bloom_mix
    candidates = _candidates(db, scope)
    if not candidates:
        raise EmptyBankError("Ngân hàng chưa có câu hỏi nào trong phạm vi đã chọn")
    candidates, notice = filter_difficulty(candidates, n, difficulty)

    reasons: dict[int, dict] = {}
    picked: list[Question] | None = None
    if mode == "weakness":
        prio, reasons = weakness_priority(db, user_id, candidates) if user_id else ({}, {})
        if any(p > 0 for p in prio.values()):
            picked = pick_weakness(candidates, prio, n, rng)
        else:
            mode = "normal"
            notice = " ".join(x for x in (notice, "Chưa đủ dữ liệu về điểm yếu của bạn trong phạm vi này: đã tạo đề "
                                                   "thường. Làm thêm vài đề để hệ thống biết bạn hay nhầm ở đâu.") if x)
    if picked is None:
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

    quiz = Quiz(scope=scope.model_dump(), num_questions=n, bloom_mix=mix, user_id=user_id,
                mode=mode if mode == "weakness" else ("difficulty" if difficulty else "normal"), difficulty=difficulty)
    db.add(quiz)
    db.flush()
    db.add_all(QuizQuestion(quiz_id=quiz.id, question_id=q.id, position=i, reason=reasons.get(q.id))
               for i, q in enumerate(picked, start=1))
    db.execute(update(Question).where(Question.id.in_([q.id for q in picked]))
               .values(times_used=Question.times_used + 1))
    db.commit()
    return QuizResult(quiz=quiz, notice=notice, reasons={q.id: reasons[q.id] for q in picked if q.id in reasons})
