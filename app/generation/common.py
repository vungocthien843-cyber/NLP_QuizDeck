"""Tiện ích dùng chung cho sinh câu hỏi, hậu kiểm và tạo đề."""
import math
import random
from dataclasses import dataclass, field

from app.models import Chunk
from app.schemas import GeneratedMCQ

LETTERS = "ABCD"


@dataclass
class ShuffledMCQ:
    options: dict[str, str]
    rationales: dict[str, str]
    answer: str
    origin: dict[str, int] = field(default_factory=dict)   # chữ cái → chỉ số của phương án trong mcq.options (v3)


def shuffle_options(mcq: GeneratedMCQ, rng: random.Random | None = None) -> ShuffledMCQ:
    """Xáo thứ tự rồi mới gán chữ cái, nên explanation / rationale luôn khớp. origin giữ lại vị trí gốc để biết
    chữ cái nào là phương án nào (trước v3 thông tin này bị mất sau khi xáo)."""
    order = list(range(len(mcq.options)))
    (rng or random).shuffle(order)
    opts = [mcq.options[i] for i in order]
    return ShuffledMCQ(
        options={LETTERS[i]: o.text for i, o in enumerate(opts)},
        rationales={LETTERS[i]: o.rationale for i, o in enumerate(opts)},
        answer=next(LETTERS[i] for i, o in enumerate(opts) if o.is_correct),
        origin={LETTERS[i]: j for i, j in enumerate(order)},
    )


def build_option_meta(mcq: GeneratedMCQ, shuffled: ShuffledMCQ, picked: list[dict] | None,
                      source_default: str = "v1") -> dict[str, dict]:
    """Kế hoạch v3, B5: chữ cái → vai trò của phương án, để biết người học chọn sai vì hiểu nhầm gì.
    picked: thông tin các đáp án nhiễu được chọn (pipeline v2/v3: text, source, error_type), khớp theo text.
    Không có (câu v1) thì source = source_default, error_type = None (gắn sau bằng scripts/backfill_option_meta)."""
    by_text = {_norm(p["text"]): p for p in picked or []}
    meta: dict[str, dict] = {}
    for letter, idx in shuffled.origin.items():
        opt = mcq.options[idx]
        if opt.is_correct:
            meta[letter] = {"role": "key"}
            continue
        p = by_text.get(_norm(opt.text), {})
        meta[letter] = {"role": "distractor", "source": p.get("source", source_default),
                        "error_type": p.get("error_type"), "candidate_id": p.get("candidate_id")}
    return meta


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def allocate(n: int, mix: dict[str, float]) -> dict[str, int]:
    """Chia n theo tỉ lệ mix bằng phương pháp phần dư lớn nhất (tổng luôn đúng bằng n)."""
    total = sum(mix.values()) or 1.0
    raw = {k: n * v / total for k, v in mix.items()}
    alloc = {k: math.floor(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - alloc[k], reverse=True)[: n - sum(alloc.values())]:
        alloc[k] += 1
    return alloc


def slide_label(chunk: Chunk) -> str:
    if chunk.slide_end and chunk.slide_end != chunk.slide_no:
        return f"{chunk.slide_no}–{chunk.slide_end}"
    return str(chunk.slide_no)


def format_options(options: dict[str, str]) -> str:
    return "\n".join(f"{letter}. {text}" for letter, text in options.items())


def format_context(chunks: list[Chunk], seed_id: int | None = None) -> str:
    parts = []
    for c in chunks:
        role = ' vai_trò="hạt giống"' if c.id == seed_id else ""
        parts.append(
            f'<chunk id={c.id} nguồn="Slide {slide_label(c)}"{role}>\n'
            f"{c.embed_text}\n</chunk>"
        )
    return "\n".join(parts)


def word_count(chunk: Chunk) -> int:
    return len(f"{chunk.raw_text} {chunk.notes or ''} {chunk.vlm_caption or ''}".split())
