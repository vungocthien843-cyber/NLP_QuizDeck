"""Hồ sơ hiểu nhầm của người học (kế hoạch v3, D3).

Mỗi cặp (ý kiến thức, loại hiểu nhầm) có một điểm, suy giảm theo thời gian (nửa đời = weakness_decay_days):
  chọn phương án sai mang loại lỗi e của ý c   → score = score·suy_giảm + 1
  trả lời đúng một câu của ý c                 → mọi loại lỗi của ý c: score = max(0, score·suy_giảm − 0,5)
Điểm cao = người học hay mắc hiểu nhầm đó gần đây. Dùng cho chế độ luyện điểm yếu và trang hồ sơ.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import MisconceptionStat, Response
from app.prompts import UNCLEAR, misconception_types

CORRECT_RELIEF = 0.5


def _decay(stat: MisconceptionStat, now: datetime) -> float:
    if stat.last_seen is None:
        return 1.0
    days = max((now - stat.last_seen).total_seconds() / 86400, 0.0)
    return 0.5 ** (days / max(get_config().learner.weakness_decay_days, 1e-6))


def update_after_attempt(db: Session, user_id: int | None, responses: list[Response],
                         now: datetime | None = None) -> None:
    """Gọi sau khi đã add các Response của một lần nộp bài (chưa commit)."""
    if user_id is None:
        return
    now = now or datetime.now(timezone.utc)
    stats = {(s.concept, s.error_type): s for s in db.scalars(
        select(MisconceptionStat).where(MisconceptionStat.user_id == user_id))}
    for r in responses:
        if not r.concept:
            continue
        if not r.is_correct and r.error_type and r.error_type != UNCLEAR:
            s = stats.get((r.concept, r.error_type))
            if s is None:
                s = MisconceptionStat(user_id=user_id, concept=r.concept, error_type=r.error_type, score=0.0, n_seen=0)
                db.add(s)
                stats[(r.concept, r.error_type)] = s
            s.score = s.score * _decay(s, now) + 1.0
            s.n_seen += 1
            s.last_seen = now
        elif r.is_correct:
            for (concept, _), s in stats.items():
                if concept == r.concept:
                    s.score = max(0.0, s.score * _decay(s, now) - CORRECT_RELIEF)
                    s.last_seen = now


def describe(error_type: str | None) -> dict | None:
    """Mô tả loại hiểu nhầm để hiển thị: {code, ten, chan_doan}; None nếu không có / khong_ro."""
    t = misconception_types().get(error_type or "")
    return {"code": error_type, "ten": t["ten"], "chan_doan": t["chan_doan"]} if t else None


def top_weaknesses(db: Session, user_id: int, k: int = 5, min_score: float = 0.5,
                   now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for s in db.scalars(select(MisconceptionStat).where(MisconceptionStat.user_id == user_id)):
        cur = s.score * _decay(s, now)
        if cur >= min_score:
            rows.append({"concept": s.concept, "error_type": s.error_type, "score": round(cur, 3),
                         "n_seen": s.n_seen, **(describe(s.error_type) or {})})
    rows.sort(key=lambda r: -r["score"])
    return rows[:k]
