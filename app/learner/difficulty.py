"""Ước lượng độ khó ban đầu của câu hỏi khi chưa có dữ liệu làm bài (kế hoạch v3, D4).

Hai tín hiệu, đổi về phân vị (0 = khó nhất, 1 = dễ nhất) để cộng được với nhau:
  gần nghĩa (MỌI câu)  1 − cos trung bình giữa 3 đáp án nhiễu và đáp án đúng (bge-m3). Đáp án nhiễu càng sát nghĩa đáp án
                       đúng thì càng khó loại → khó. Tính một lần, lưu ở selection["mean_cos_dk"].
  margin (câu v2/v3)   xác suất reranker của đáp án đúng trừ của đáp án nhiễu mạnh nhất; nhỏ = khó.
x = trung bình các phân vị có được + thưởng Bloom (remember +0,1 · understand 0 · apply −0,1).
Chia ba mức theo THỨ HẠNG của x (learner.difficulty_quantiles) nên mỗi mức có số câu gần bằng nhau.

Lần chạy đầu (14/11) chỉ dùng margin: 511 câu v1 không có margin nhận cùng một giá trị nên dồn hết vào "medium"
(19 / 410 / 131). Tín hiệu gần nghĩa có ở mọi câu nên sửa được việc đó.
Khi có đủ dữ liệu làm bài, nhóm E sẽ hiệu chỉnh lại bằng tỉ lệ trả lời đúng thực tế.
"""
import logging
from collections.abc import Callable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import Question

log = logging.getLogger(__name__)
BLOOM_BONUS = {"remember": 0.1, "understand": 0.0, "apply": -0.1}
LEVELS = ("easy", "medium", "hard")


def margin_of(q: Question) -> float | None:
    m = (q.selection or {}).get("margin")
    return float(m) if isinstance(m, (int, float)) else None


def _default_embed(texts: list[str]) -> np.ndarray:
    from app.retrieval.embedder import get_embedder

    vecs = np.stack([r.dense for r in get_embedder().encode(texts)])
    return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)


def fill_mean_cos(qs: list[Question], embed: Callable[[list[str]], np.ndarray] | None = None) -> int:
    """Tính selection["mean_cos_dk"] cho câu chưa có. Trả số câu vừa tính."""
    todo = [q for q in qs if not isinstance((q.selection or {}).get("mean_cos_dk"), (int, float))]
    if not todo:
        return 0
    embed = embed or _default_embed
    for start in range(0, len(todo), 64):
        batch = todo[start:start + 64]
        texts = [t for q in batch for t in (q.options[q.answer], *[v for k, v in q.options.items() if k != q.answer])]
        vecs = embed(texts)
        for i, q in enumerate(batch):
            key, dis = vecs[4 * i], vecs[4 * i + 1:4 * i + 4]
            q.selection = {**(q.selection or {}), "mean_cos_dk": round(float(np.mean(dis @ key)), 4)}
    return len(todo)


def _percentile(values: dict[int, float]) -> dict[int, float]:
    """Phân vị theo thứ hạng (0..1), hoà nhau lấy hạng trung bình."""
    if not values:
        return {}
    order = sorted(values, key=lambda k: values[k])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in order[i:j + 1]:
            ranks[k] = (i + j) / 2
        i = j + 1
    n = max(len(order) - 1, 1)
    return {k: r / n for k, r in ranks.items()}


def assign_levels(db: Session, embed: Callable[[list[str]], np.ndarray] | None = None) -> dict[str, int]:
    """Tính lại difficulty_est cho mọi câu accepted. Lần đầu nhúng phương án của các câu chưa có mean_cos_dk
    (bge-m3, vài phút trên CPU với vài trăm câu); các lần sau chỉ nhúng câu mới."""
    qs = list(db.scalars(select(Question).where(Question.status == "accepted")))
    if not qs:
        return {}
    n_new = fill_mean_cos(qs, embed)
    p_cos = _percentile({q.id: 1 - q.selection["mean_cos_dk"] for q in qs})
    p_margin = _percentile({q.id: m for q in qs if (m := margin_of(q)) is not None})
    xs = {}
    for q in qs:
        parts = [p_cos[q.id]] + ([p_margin[q.id]] if q.id in p_margin else [])
        xs[q.id] = sum(parts) / len(parts) + BLOOM_BONUS.get(q.bloom_level or "", 0.0)
    order = sorted(qs, key=lambda q: (xs[q.id], q.id))        # khó → dễ
    q_lo, q_hi = get_config().learner.difficulty_quantiles
    cut_lo, cut_hi = round(q_lo * len(order)), round(q_hi * len(order))
    counts = {lv: 0 for lv in LEVELS}
    for rank, q in enumerate(order):
        level = "hard" if rank < cut_lo else "medium" if rank < cut_hi else "easy"
        q.difficulty_est = level
        counts[level] += 1
    db.commit()
    log.info("Mức độ khó: %s (vừa tính gần nghĩa cho %d câu)", counts, n_new)
    return counts


def level_like_bank(db: Session, qs: list[Question], embed: Callable[[list[str]], np.ndarray] | None = None) -> dict:
    """Gán difficulty_est cho các câu NGOÀI ngân hàng (ví dụ câu thử nghiệm, status='experiment') theo đúng ngưỡng
    của ngân hàng accepted, KHÔNG đổi mức của câu ngân hàng. Không commit."""
    bank = list(db.scalars(select(Question).where(Question.status == "accepted")))
    pool = bank + [q for q in qs if q not in bank]
    fill_mean_cos(pool, embed)
    p_cos = _percentile({q.id: 1 - q.selection["mean_cos_dk"] for q in pool})
    p_margin = _percentile({q.id: m for q in pool if (m := margin_of(q)) is not None})

    def x(q: Question) -> float:
        parts = [p_cos[q.id]] + ([p_margin[q.id]] if q.id in p_margin else [])
        return sum(parts) / len(parts) + BLOOM_BONUS.get(q.bloom_level or "", 0.0)

    counts = {lv: 0 for lv in LEVELS}
    if bank:
        xs = sorted(x(q) for q in bank)                       # khó → dễ
        q_lo, q_hi = get_config().learner.difficulty_quantiles
        t_lo = xs[min(round(q_lo * len(xs)), len(xs) - 1)]
        t_hi = xs[min(round(q_hi * len(xs)), len(xs) - 1)]
    else:                                                     # chưa có ngân hàng: chia theo chính các câu này
        xs = sorted(x(q) for q in qs)
        t_lo, t_hi = xs[len(xs) // 3], xs[2 * len(xs) // 3]
    for q in qs:
        v = x(q)
        q.difficulty_est = "hard" if v < t_lo else "medium" if v < t_hi else "easy"
        counts[q.difficulty_est] += 1
    return counts
