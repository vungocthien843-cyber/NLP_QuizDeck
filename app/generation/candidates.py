"""Bước 3 của pipeline v2: lấy ứng viên đáp án nhiễu từ nhiều nguồn (K3).

- vit5: model tự fine-tune (training/), diverse beam search → tối đa max_vit5_keep ứng viên.
- llm:  2–3 ứng viên kiểu hiểu lầm có chủ đích, mỗi ứng viên kèm loại lỗi (prompt mcq_misconception).
Hai nguồn khác nhau về bản chất (model nhỏ học từ dữ liệu vs LLM lớn), nên ứng viên đa dạng hơn một nguồn.
"""
import asyncio
import logging
from dataclasses import asdict, dataclass

from app.config import get_config
from app.generation.filters import normalize_key
from app.llm_client import JSON_MODE, acomplete, parse_json
from app.prompts import UNCLEAR, error_types_block, normalize_error_type, render

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    text: str
    source: str                        # vit5 | llm
    error_type: str | None = None
    error_type_self: str | None = None  # nhãn LLM tự khai lúc sinh (chỉ nguồn llm); error_type là nhãn sau bước gắn nhãn
    copy_score: float | None = None
    entail_prob: float | None = None
    score: float | None = None
    rejected_at: str | None = None     # form | copy | nli | None (còn dùng được)
    selected: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


async def from_vit5(stem: str, answer: str, context: str, decoding: str | None = None,
                    notes: list | None = None) -> list[Candidate]:
    """notes (nếu truyền): ghi trạng thái nguồn vit5 của lần gọi này vào report của câu hỏi, để lỗi không chỉ
    nằm trong log (lần chạy 06/11 không biết được vì sao ViT5 không có ứng viên nào)."""
    from app.local_models import get_generator, vit5_available

    def note(status: str, **extra) -> None:
        if notes is not None:
            notes.append({"status": status, **extra})

    cfg = get_config().distractor
    if "vit5" not in cfg.sources:
        return []
    if not vit5_available():
        log.warning("Chưa có checkpoint ViT5 ở %s: bỏ qua nguồn vit5.", cfg.vit5_checkpoint)
        note("unavailable", checkpoint=cfg.vit5_checkpoint)
        return []
    try:
        texts = await asyncio.to_thread(get_generator().generate, stem, answer, context, cfg.n_candidates,
                                        decoding or cfg.decoding)
    except Exception as exc:  # model hỏng không được làm hỏng cả câu hỏi: bỏ nguồn vit5, vẫn dùng ứng viên LLM
        log.warning("Nguồn vit5 lỗi, bỏ qua (%s: %s)", type(exc).__name__, exc)
        note("error", error=f"{type(exc).__name__}: {exc}"[:300])
        return []
    kept = dedupe(texts, answer)[:cfg.max_vit5_keep]
    note("ok", raw=len(texts), kept=len(kept))
    return [Candidate(t, "vit5") for t in kept]


def length_hint(answer: str) -> dict[str, int]:
    w = max(len(answer.split()), 1)
    return {"answer_words": w, "len_lo": max(1, round(w * 0.7)), "len_hi": max(2, round(w * 1.25))}


async def from_llm(context: str, stem: str, answer: str, key_point: str, bloom_level: str,
                   n: int | None = None, avoid: list[str] | None = None, calls: list | None = None,
                   neighbors: list[str] | None = None) -> list[Candidate]:
    cfg = get_config()
    n = n or cfg.distractor.llm_candidates
    if "llm" not in cfg.distractor.sources or n <= 0:
        return []
    prompt = render("mcq_misconception", context=context, stem=stem, answer=answer, key_point=key_point,
                    bloom_level=bloom_level, n=n, avoid="\n".join(f"- {a}" for a in avoid or []) or "(không có)",
                    error_types=error_types_block(),
                    neighbors="\n".join(f"- {x}" for x in neighbors or []) or "(không có)",
                    # G1 (15/11): ứng viên LLM thường dài hơn key → key ngắn nhất 41% câu. Cho số từ cụ thể.
                    **length_hint(answer))
    res = await acomplete("mcq_generator", [{"role": "user", "content": prompt}],
                          temperature=cfg.llm.temperature_generate, response_format=JSON_MODE)
    if calls is not None:
        calls.append({"step": "mcq_misconception", "in": res.prompt_tokens, "out": res.completion_tokens,
                      "cost": res.cost_usd})
    data = parse_json(res.text)
    items = data.get("candidates") or []
    out = []
    for it in items:
        if isinstance(it, str):
            it = {"text": it}
        text = str(it.get("text") or "").strip()
        if text:
            label = normalize_error_type(it.get("error_type"))
            out.append(Candidate(text, "llm", error_type=label, error_type_self=label))
    return out[:n]


async def tag_misconceptions(context: str, stem: str, answer: str, key_point: str, cands: list[Candidate],
                             calls: list | None = None) -> dict:
    """Kế hoạch v3, B2: gắn MỘT loại hiểu nhầm cho mỗi ứng viên còn sống (cả nguồn vit5 vốn không có nhãn), bằng
    một lần gọi LLM cho cả lô. Ứng viên LLM giữ nhãn tự khai ở error_type_self; error_type lấy nhãn mới.
    "khong_ro" = phương án sai không thể hiện hiểu nhầm cụ thể (bước chọn bộ sẽ trừ điểm).
    Gọi lỗi hoặc JSON hỏng thì giữ nguyên nhãn cũ, không làm hỏng câu hỏi. Trả thống kê để ghi vào report."""
    todo = [c for c in cands if c.rejected_at is None]
    if not todo:
        return {"tagged": 0}
    listing = "\n".join(f"{i}. {c.text}" for i, c in enumerate(todo))
    prompt = render("mcq_tag_error", context=context, stem=stem, answer=answer, key_point=key_point,
                    error_types=error_types_block(with_cues=True), candidates=listing)
    try:
        res = await acomplete("mcq_generator", [{"role": "user", "content": prompt}],
                              temperature=get_config().llm.temperature_judge, response_format=JSON_MODE)
        if calls is not None:
            calls.append({"step": "mcq_tag_error", "in": res.prompt_tokens, "out": res.completion_tokens,
                          "cost": res.cost_usd})
        labels = parse_json(res.text).get("labels") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("Gắn nhãn hiểu nhầm lỗi, giữ nhãn cũ (%s: %s)", type(exc).__name__, exc)
        return {"tagged": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
    n = 0
    for it in labels:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        label = normalize_error_type(it.get("error_type"), allow_unclear=True)
        if 0 <= i < len(todo) and label:
            todo[i].error_type = label
            n += 1
    return {"tagged": n, "of": len(todo), "unclear": sum(c.error_type == UNCLEAR for c in todo)}


def dedupe(texts: list[str], answer: str) -> list[str]:
    """Bỏ rỗng, bỏ trùng nhau sau chuẩn hoá, bỏ trùng nguyên văn đáp án đúng; giữ thứ tự."""
    seen, out = {normalize_key(answer)}, []
    for t in texts:
        k = normalize_key(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out


def merge(*groups: list[Candidate], answer: str) -> list[Candidate]:
    seen, out = {normalize_key(answer)}, []
    for g in groups:
        for c in g:
            k = normalize_key(c.text)
            if k and k not in seen:
                seen.add(k)
                out.append(c)
    return out
