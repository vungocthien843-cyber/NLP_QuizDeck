"""Pipeline v2: sinh MỘT câu hỏi qua 8 bước (docs/ke-hoach-v2.md, mục 7).

  1. LLM  chọn ý hỏi + đáp án đúng + evidence nguyên văn + loại đáp án      (prompt mcq_key)
  2. LLM  viết stem khi đã biết đáp án                                        (prompt mcq_stem)
  3a. ViT5 fine-tune sinh ứng viên đáp án nhiễu (K1–K3)  3b. LLM sinh 2–3 ứng viên kiểu hiểu lầm
  4. luật: lọc hình thức + chép đáp án (K5)      5. NLI: lọc ứng viên mà ngữ cảnh chứng minh là đúng
  6. chấm điểm + chọn bộ 3 bằng entropy có ràng buộc δ (K4); không bộ nào đạt → sinh bù rồi chọn lại
  7. LLM  viết giải thích cho từng phương án                                  (prompt mcq_explain)
  8. (trong bank_builder) validator v1 + chống trùng + lưu kèm metadata của mọi ứng viên

Trả về GeneratedMCQ như v1, nên phần hậu kiểm, chống trùng, lưu, tạo đề và giao diện dùng lại được nguyên.
"""
import asyncio
import contextlib
import logging
import random
import re
import time

from app.config import get_config
from app.generation import candidates as cand_mod
from app.generation import filters, selector
from app.generation.common import format_context
from app.generation.validator import _CONTEXT_REF, EVIDENCE_MIN_COVERAGE, evidence_coverage, normalize
from app.llm_client import JSON_MODE, acomplete, parse_json
from app.models import Chunk
from app.prompts import PROMPT_DIR, render
from app.schemas import GeneratedMCQ

log = logging.getLogger(__name__)
ANSWER_TYPES = {"thuat_ngu", "dinh_nghia", "thuoc_tinh", "buoc_quy_trinh", "so_sanh", "nhan_qua",
                "con_so_cong_thuc", "tinh_huong"}


class StepFailed(Exception):
    """Một bước trượt; feedback được đưa vào prompt của lần sinh lại (giống v1)."""

    def __init__(self, step: str, feedback: str, details: dict | None = None):
        super().__init__(f"{step}: {feedback}")
        self.step, self.feedback, self.details = step, feedback, details or {}


def _bloom_guide(level: str) -> str:
    import json
    return json.loads((PROMPT_DIR / "mcq_bloom.json").read_text(encoding="utf-8"))[level]


async def _ask(prompt_name: str, calls: list, **values) -> dict:
    cfg = get_config()
    messages = [{"role": "system", "content": render("mcq_system", course_name=cfg.course.name)},
                {"role": "user", "content": render(prompt_name, **values)}]
    res = await acomplete("mcq_generator", messages, temperature=cfg.llm.temperature_generate,
                          response_format=JSON_MODE)
    calls.append({"step": prompt_name, "in": res.prompt_tokens, "out": res.completion_tokens, "cost": res.cost_usd})
    return parse_json(res.text)


@contextlib.contextmanager
def _timed(timing: dict, step: str):
    """Ghi thời gian (giây) của một bước vào report["timing"] (kế hoạch v3, việc A5). Bước trượt thì thời gian
    vẫn được ghi vào exc.details["timing"] để biết câu trượt tốn bao lâu."""
    t0 = time.perf_counter()
    try:
        yield
    except StepFailed as exc:
        timing[step] = round(time.perf_counter() - t0, 2)
        exc.details.setdefault("timing", dict(timing))
        raise
    timing[step] = round(time.perf_counter() - t0, 2)


def _feedback_block(feedback: str | None) -> str:
    return f"\nLẦN TRƯỚC BỊ LOẠI VÌ: {feedback}\nSửa đúng lỗi này.\n" if feedback else ""


# ---------- Bước 1–2 ----------
async def step_key(seed, context: list[Chunk], stems: str, feedback: str | None, calls: list) -> dict:
    data = await _ask("mcq_key", calls, context=format_context(context, seed_id=seed.chunk.id),
                      seed_id=seed.chunk.id, bloom_guide=_bloom_guide(seed.bloom_level), existing_stems=stems,
                      feedback=_feedback_block(feedback), bloom_level=seed.bloom_level)
    key = {k: str(data.get(k) or "").strip() for k in ("key_point", "evidence", "answer", "answer_type")}
    key["source_chunk_ids"] = [int(i) for i in data.get("source_chunk_ids") or [] if str(i).isdigit()] or [seed.chunk.id]
    if seed.chunk.id not in key["source_chunk_ids"]:
        key["source_chunk_ids"].insert(0, seed.chunk.id)
    if key["answer_type"] not in ANSWER_TYPES:
        key["answer_type"] = "khac"
    if not key["answer"]:
        raise StepFailed("key", "Thiếu đáp án đúng (answer).")
    best = max((evidence_coverage(key["evidence"], f"{c.raw_text}\n{c.notes or ''}\n{c.vlm_caption or ''}")
                for c in context), default=0.0)
    if len(normalize(key["evidence"]).split()) < 4 or best < EVIDENCE_MIN_COVERAGE:
        raise StepFailed("key", "evidence không khớp nguyên văn với NGỮ CẢNH. Chép đúng từng chữ câu chứng minh "
                                "đáp án đúng; nếu không có câu nào như vậy thì đổi sang ý khác.",
                         {"coverage": round(best, 3)})
    return key


async def step_stem(seed, context: list[Chunk], key: dict, stems: str, feedback: str | None, calls: list) -> str:
    for attempt in range(2):
        data = await _ask("mcq_stem", calls, context=format_context(context, seed_id=seed.chunk.id),
                          key_point=key["key_point"], answer=key["answer"], answer_type=key["answer_type"],
                          evidence=key["evidence"], bloom_guide=_bloom_guide(seed.bloom_level),
                          existing_stems=stems, feedback=_feedback_block(feedback), bloom_level=seed.bloom_level)
        stem = str(data.get("stem") or "").strip()
        ans = normalize(key["answer"])
        if not stem:
            feedback = "stem rỗng."
        elif len(ans.split()) >= 3 and ans in normalize(stem):
            feedback = "Câu hỏi đang chứa nguyên văn đáp án đúng. Diễn đạt lại để không lộ đáp án."
        elif m := _CONTEXT_REF.search(stem):
            feedback = f"Người làm bài không thấy ngữ cảnh: bỏ cụm \"{m.group(0)}\", câu hỏi phải tự đứng được."
        else:
            return stem
    raise StepFailed("stem", feedback or "stem không hợp lệ")


# ---------- Bước 3–6 ----------
def neighbor_concepts(seed, context: list[Chunk], key_point: str, n: int) -> list[str]:
    """Kế hoạch v3, B3: n khái niệm gần với ý được hỏi nhưng NẰM NGOÀI ngữ cảnh đã đưa cho LLM, lấy bằng truy xuất
    hybrid. Phạm vi: các bài cùng course_id; tài liệu chưa gán course_id thì trong cùng bài. Lỗi thì trả rỗng."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Document
    from app.retrieval.hybrid import retrieve
    from app.schemas import Scope

    if n <= 0 or not key_point:
        return []
    try:
        with SessionLocal() as db:
            doc = db.get(Document, seed.chunk.document_id)
            docs = [seed.chunk.document_id]
            if doc is not None and doc.course_id is not None:
                # Không lấy khái niệm từ slide riêng của người khác
                docs = list(db.scalars(select(Document.id).where(
                    Document.course_id == doc.course_id, Document.is_active,
                    Document.is_shared | (Document.owner_user_id == doc.owner_user_id))))
            hits = retrieve(db, key_point, Scope(document_ids=docs), k=n * 4, exclude_ids={c.id for c in context})
    except Exception as exc:  # noqa: BLE001  thiếu khái niệm lân cận không được làm hỏng câu hỏi
        log.warning("Không lấy được khái niệm lân cận (%s: %s)", type(exc).__name__, exc)
        return []
    out: list[str] = []
    for h in hits:
        text = clean_slide_text(f"{h.title}: {h.raw_text}" if h.title else h.raw_text or "")
        if is_admin_slide(text) or not text:
            continue
        snippet = " ".join(text.split()[:30])
        if snippet not in out:
            out.append(snippet)
        if len(out) >= n:
            break
    return out


# Slide "hành chính" (lộ trình, chuẩn đầu ra, mục lục...) không phải khái niệm: lần chạy 14/11 thấy RAG trả về các
# slide này làm "khái niệm lân cận". So khớp trên 80 ký tự đầu, đã chuẩn hoá.
_ADMIN = re.compile(r"lộ trình|chuẩn đầu ra|\bclo\d*\b|mục lục|nội dung (chính|hôm nay|bài học)|mục tiêu (bài|chương)|"
                    r"tài liệu tham khảo|think\s*[–-]\s*pair|cảm ơn|câu hỏi ôn tập|bài tập về nhà", re.I)


def is_admin_slide(text: str) -> bool:
    return bool(_ADMIN.search(text[:80]))


def clean_slide_text(text: str) -> str:
    """Bỏ cụm từ lặp liền nhau do trích slide ("hôm nay hôm nay", "cho cho đúng đúng", "đếm chia đếm đếm chia đếm")."""
    words = text.split()
    changed = True
    while changed:
        changed = False
        for n in (3, 2, 1):
            i = 0
            while i + 2 * n <= len(words):
                if [w.lower() for w in words[i:i + n]] == [w.lower() for w in words[i + n:i + 2 * n]]:
                    del words[i + n:i + 2 * n]
                    changed = True
                else:
                    i += 1
    return " ".join(words)


async def _clock(dt: dict | None, name: str, coro):
    """Chạy coroutine và cộng thời gian (giây) vào dt[name] — đo chi tiết bên trong bước đáp án nhiễu (A5)."""
    t0 = time.perf_counter()
    try:
        return await coro
    finally:
        if dt is not None:
            dt[name] = round(dt.get(name, 0) + time.perf_counter() - t0, 2)


async def _collect(seed, key: dict, stem: str, context_text: str, avoid: list[str], refill: bool,
                   calls: list, vit5_notes: list | None = None, neighbors: list[str] | None = None,
                   dt: dict | None = None) -> list:
    cfg = get_config().distractor
    n_llm = cfg.llm_candidates + (2 if refill else 0)
    vit5, llm = await asyncio.gather(
        _clock(dt, "vit5", cand_mod.from_vit5(stem, key["answer"], seed.chunk.embed_text,
                                              decoding="sampling" if refill else None, notes=vit5_notes)),
        _clock(dt, "llm", cand_mod.from_llm(context_text, stem, key["answer"], key["key_point"], seed.bloom_level,
                                            n=n_llm, avoid=avoid, calls=calls, neighbors=neighbors)),
    )
    return [*vit5, *llm]


async def step_distractors(seed, context: list[Chunk], key: dict, stem: str, calls: list) -> tuple[list, dict]:
    cfg = get_config().distractor
    context_text = format_context(context)
    premise = filters.nli_premise(key["evidence"], seed.chunk.embed_text, stem, key["answer"])
    pool: list = []
    info: dict = {}
    key_entail = None
    nli_modes: list[str] = []
    vit5_notes: list[dict] = []
    tag_stats: list[dict] = []
    dt: dict[str, float] = {}
    neighbors = await _clock(dt, "neighbors", asyncio.to_thread(neighbor_concepts, seed, context, key["key_point"],
                                                                cfg.neighbor_concepts))
    for round_no in range(cfg.refill_rounds + 1):
        new = await _collect(seed, key, stem, context_text, [c.text for c in pool], round_no > 0, calls, vit5_notes,
                             neighbors, dt)
        new = cand_mod.merge(new, answer=key["answer"])
        new = [c for c in new if filters.normalize_key(c.text) not in {filters.normalize_key(p.text) for p in pool}]
        filters.apply_rule_filters(new, key["answer"])
        entail, nli_mode = await _clock(dt, "nli", asyncio.to_thread(filters.apply_nli_filter, new, stem,
                                                                     key["answer"], premise))
        key_entail = entail if key_entail is None else key_entail
        nli_modes.append(nli_mode)
        if cfg.tag_errors:
            tag_stats.append(await _clock(dt, "tag", cand_mod.tag_misconceptions(
                context_text, stem, key["answer"], key["key_point"], new, calls)))
        pool += new
        alive = [c for c in pool if c.rejected_at is None]
        if len(alive) < cfg.min_alive and round_no < cfg.refill_rounds:
            continue                     # v3 (A3): quá ít ứng viên để chọn → sinh bù trước rồi mới chọn bộ
        if len(alive) >= 3:
            key_score, scores = await _clock(dt, "score", selector.score(
                cfg.scorer, context_text, key["evidence"], stem, key["answer"], [c.text for c in alive]))
            for c, s in zip(alive, scores, strict=True):
                c.score = round(s, 4)
            chosen, info = selector.select(key_score, scores, cfg.selection, cfg.delta, rng=random.Random(seed.chunk.id),
                                           texts=[c.text for c in alive], key_text=key["answer"],
                                           error_types=[c.error_type for c in alive] if cfg.tag_errors else None)
            info.update(scorer=cfg.scorer, key_score=round(key_score, 4), round=round_no, key_entail=key_entail,
                        nli_modes=nli_modes, vit5=vit5_notes, tagging=tag_stats, neighbors=neighbors, timing_detail=dt)
            if chosen is not None:
                for i in chosen:
                    alive[i].selected = True
                picked = [alive[i] for i in chosen]
                return picked, {**info, "pool": [c.as_dict() for c in pool]}
        else:
            info = {"reason": "not_enough_candidates", "n_alive": len(alive), "round": round_no,
                    "key_entail": key_entail, "nli_modes": nli_modes, "vit5": vit5_notes, "tagging": tag_stats,
                    "timing_detail": dt}
    raise StepFailed("selection",
                     "Không chọn được 3 phương án sai vừa hợp lý vừa chắc chắn sai. Chọn ý hỏi khác rõ ràng hơn.",
                     {**info, "pool": [c.as_dict() for c in pool]})


# ---------- Bước 7 ----------
async def step_explain(context: list[Chunk], key: dict, stem: str, options: list[str], calls: list) -> tuple[list[str], str]:
    listing = "\n".join(f"- {'(ĐÚNG) ' if i == 0 else '(SAI) '}{o}" for i, o in enumerate(options))
    data = await _ask("mcq_explain", calls, context=format_context(context), evidence=key["evidence"], stem=stem,
                      options=listing, n=len(options))
    rationales = [str(r).strip() for r in data.get("rationales") or []]
    if len(rationales) != len(options):
        rationales = (rationales + [""] * len(options))[:len(options)]
    if not rationales[0]:
        rationales[0] = f"Đúng theo slide: {key['evidence']}"
    explanation = str(data.get("explanation") or "").strip() or key["key_point"]
    return rationales, explanation


async def generate(seed, context: list[Chunk], existing_stems: list[str], feedback: str | None = None,
                   max_existing: int = 30) -> tuple[GeneratedMCQ, dict]:
    calls: list[dict] = []
    timing: dict[str, float] = {}
    stems = "\n".join(f"- {s}" for s in existing_stems[-max_existing:]) or "(chưa có)"
    with _timed(timing, "key"):
        key = await step_key(seed, context, stems, feedback, calls)
    with _timed(timing, "stem"):
        stem = await step_stem(seed, context, key, stems, None, calls)
    with _timed(timing, "distractors"):
        picked, selection = await step_distractors(seed, context, key, stem, calls)
    options = [key["answer"], *[c.text for c in picked]]
    with _timed(timing, "explain"):
        rationales, explanation = await step_explain(context, key, stem, options, calls)
    mcq = GeneratedMCQ.model_validate({
        "key_point": key["key_point"], "evidence": key["evidence"], "stem": stem,
        "options": [{"text": o, "is_correct": i == 0, "rationale": r}
                    for i, (o, r) in enumerate(zip(options, rationales, strict=True))],
        "explanation": explanation, "bloom_level": seed.bloom_level,
        "source_chunk_ids": key["source_chunk_ids"],
    })
    pool = selection.pop("pool")
    report = {"pipeline_version": "v2", "answer_type": key["answer_type"], "selection": selection,
              "candidates": pool, "llm_calls": calls, "timing": timing,
              "picked": [{"text": c.text, "source": c.source, "error_type": c.error_type} for c in picked]}
    return mcq, report
