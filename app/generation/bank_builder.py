"""Sinh ngân hàng câu hỏi sau khi nạp slide (mục 7). Prompt: app/prompts/mcq_*.txt, mcq_bloom.json, few_shot.json.

Không dùng LLM để chấm lại: chất lượng được giữ bằng (1) prompt chặt theo từng mức Bloom, bắt LLM nêu
key_point và trích evidence nguyên văn trước khi viết câu hỏi; (2) hậu kiểm bằng luật (validator.py);
(3) khi trượt, lý do trượt được đưa vào prompt của lần sinh lại.
"""
import asyncio
import json
import logging
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.generation.common import allocate, format_context, shuffle_options, word_count
from app.generation.validator import check_duplicate, feedback_for, validate
from app.llm_client import JSON_MODE, acomplete, parse_json
from app.models import Chunk, Document, Question
from app.prompts import PROMPT_DIR, render
from app.retrieval.embedder import get_embedder
from app.retrieval.hybrid import retrieve
from app.schemas import BloomLevel, GeneratedMCQ, Scope

log = logging.getLogger(__name__)

MAX_EXISTING_STEMS = 30     # giới hạn số stem đưa vào prompt để tránh trùng
MAX_FEW_SHOT = 3


@dataclass
class Seed:
    chunk: Chunk
    bloom_level: BloomLevel


@dataclass
class BankState:
    document_id: int
    session_no: int | None
    target: int
    existing_stems: list[str]
    accepted: int = 0
    rejected: int = 0
    failed: int = 0                         # lỗi gọi LLM / JSON hỏng, không lưu được câu
    last_error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------- Prompt ----------
@lru_cache
def _few_shot_examples() -> list[dict]:
    path = PROMPT_DIR / "few_shot.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _few_shot(bloom_level: BloomLevel) -> str:
    """Ưu tiên ví dụ cùng mức Bloom với hạt giống, sau đó tới các mức khác."""
    examples = sorted(_few_shot_examples(), key=lambda e: e.get("bloom_level") != bloom_level)[:MAX_FEW_SHOT]
    if not examples:
        return "(chưa có)"
    return "\n\n".join(json.dumps(e, ensure_ascii=False) for e in examples)


@lru_cache
def _bloom_guides() -> dict[str, str]:
    return json.loads((PROMPT_DIR / "mcq_bloom.json").read_text(encoding="utf-8"))


def _feedback_block(feedback: str | None) -> str:
    if not feedback:
        return ""
    return f"\nLẦN TRƯỚC CÂU HỎI BỊ LOẠI VÌ: {feedback}\nViết câu mới và sửa đúng lỗi này.\n"


# ---------- Hạt giống và ngữ cảnh ----------
def select_seeds(chunks: list[Chunk], target: int, rng: random.Random | None = None) -> list[Seed]:
    """Lọc chunk đủ chữ, rải đều theo thứ tự slide, số hạt giống = target × oversample,
    gán mức Bloom theo bank.bloom_mix."""
    cfg = get_config().bank
    rng = rng or random.Random()
    eligible = [c for c in chunks if word_count(c) >= cfg.min_seed_words] or chunks
    if not eligible or target <= 0:
        return []
    num = math.ceil(target * cfg.oversample)
    if num <= len(eligible):
        picked = [eligible[math.floor(i * len(eligible) / num)] for i in range(num)]
    else:  # ít slide hơn số câu cần: quay vòng, mỗi lượt với mức Bloom khác
        picked = [eligible[i % len(eligible)] for i in range(num)]
    levels = [lvl for lvl, cnt in allocate(num, cfg.bloom_mix).items() for _ in range(cnt)]
    rng.shuffle(levels)
    return [Seed(chunk=c, bloom_level=lvl) for c, lvl in zip(picked, levels, strict=True)]


def _load_context(seed: Seed) -> list[Chunk]:
    """Hạt giống + context_k chunk liên quan trong cùng tài liệu."""
    cfg = get_config().bank
    with SessionLocal() as db:
        related = retrieve(db, seed.chunk.embed_text, Scope(document_ids=[seed.chunk.document_id]),
                           k=cfg.context_k, exclude_ids={seed.chunk.id})
        extra = list(db.scalars(select(Chunk).where(Chunk.id.in_([r.chunk_id for r in related]))))
    return [seed.chunk, *extra]


# ---------- Sinh ----------
async def generate_one(seed: Seed, context: list[Chunk], existing_stems: list[str],
                       feedback: str | None = None) -> GeneratedMCQ:
    """Gọi model `mcq_generator` ở chế độ JSON, kiểm tra schema bằng Pydantic (1 câu / lần)."""
    cfg = get_config()
    stems = existing_stems[-MAX_EXISTING_STEMS:]
    messages = [
        {"role": "system", "content": render("mcq_system", course_name=cfg.course.name)},
        {"role": "user", "content": render(
            "mcq_user",
            few_shot=_few_shot(seed.bloom_level),
            context=format_context(context, seed_id=seed.chunk.id),
            seed_id=seed.chunk.id,
            bloom_guide=_bloom_guides()[seed.bloom_level],
            existing_stems="\n".join(f"- {s}" for s in stems) or "(chưa có)",
            feedback=_feedback_block(feedback),
            bloom_level=seed.bloom_level,     # thay sau cùng vì bloom_guide cũng có thể chứa {bloom_level}
        )},
    ]
    result = await acomplete("mcq_generator", messages, temperature=cfg.llm.temperature_generate,
                             response_format=JSON_MODE)
    return GeneratedMCQ.model_validate(parse_json(result.text))


def _save(state: BankState, seed: Seed, mcq: GeneratedMCQ, status: str, report: dict, stem_embedding=None) -> None:
    shuffled = shuffle_options(mcq)
    with SessionLocal() as db:
        db.add(Question(
            document_id=state.document_id,
            session_no=state.session_no,
            stem=mcq.stem,
            options=shuffled.options,
            answer=shuffled.answer,
            rationales=shuffled.rationales,
            explanation=mcq.explanation,
            bloom_level=seed.bloom_level,   # mức yêu cầu; mức LLM tự ghi nằm trong validation
            source_chunk_ids=mcq.source_chunk_ids,
            status=status,
            validation=report,
            stem_embedding=stem_embedding,
        ))
        db.commit()


def _embed_for_dedup(mcq: GeneratedMCQ):
    correct = next(o.text for o in mcq.options if o.is_correct)
    return get_embedder().encode_one(f"{mcq.stem}\n{correct}").dense


async def process_seed(seed: Seed, sem: asyncio.Semaphore, state: BankState) -> None:
    """retrieve ngữ cảnh → sinh → hậu kiểm bằng luật → chống trùng. Trượt thì sinh lại (tối đa
    bank.max_retries lần) kèm lý do trượt trong prompt. Mọi câu ứng viên đều được lưu (accepted / rejected)."""
    cfg = get_config().bank
    async with sem:
        if state.accepted >= state.target:
            return
        context = await asyncio.to_thread(_load_context, seed)
        feedback: str | None = None
        for attempt in range(cfg.max_retries + 1):
            if state.accepted >= state.target:
                return
            try:
                mcq = await generate_one(seed, context, state.existing_stems, feedback)
            except (ValidationError, ValueError) as exc:   # JSON hỏng / sai schema
                state.failed += 1
                state.last_error = f"output sai schema: {exc}"
                feedback = f"Output lần trước sai định dạng JSON yêu cầu ({str(exc).splitlines()[0][:200]})."
                log.info("Seed chunk %s lần %d: output sai schema: %s", seed.chunk.id, attempt, exc)
                continue
            except Exception as exc:
                state.failed += 1
                state.last_error = f"gọi LLM lỗi: {exc}"
                log.warning("Seed chunk %s lần %d: gọi LLM lỗi", seed.chunk.id, attempt, exc_info=True)
                continue

            result, report = validate(mcq, context, seed.chunk.id)
            report.update(attempt=attempt, feedback_used=feedback, llm_bloom_level=mcq.bloom_level,
                          key_point=mcq.key_point, evidence_text=mcq.evidence)
            if not result.passed:
                state.rejected += 1
                feedback = feedback_for(result)
                await asyncio.to_thread(_save, state, seed, mcq, "rejected", report)
                continue

            stem_embedding = await asyncio.to_thread(_embed_for_dedup, mcq)
            async with state.lock:   # tránh hai câu giống nhau sinh song song cùng lọt
                if state.accepted >= state.target:
                    return
                with SessionLocal() as db:
                    dup = check_duplicate(db, stem_embedding, cfg.dedup_threshold)
                report["duplicate"] = dup.as_dict()
                status = "accepted" if dup.passed else "rejected"
                await asyncio.to_thread(_save, state, seed, mcq, status, report, stem_embedding)
                if dup.passed:
                    state.accepted += 1
                    state.existing_stems.append(mcq.stem)
                    return
                state.rejected += 1
                feedback = feedback_for(dup)


async def build_bank(document_id: int, slide_from: int | None = None, slide_to: int | None = None,
                     n: int | None = None) -> str | None:
    """Mục tiêu mặc định = số slide × questions_per_slide; chạy song song theo bank.concurrency.
    Trả về thông báo lỗi khi không sinh được câu nào vì lỗi gọi LLM, để hiện cho người dùng."""
    cfg = get_config().bank
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        stmt = select(Chunk).where(Chunk.document_id == document_id, Chunk.is_active)
        if slide_from:
            stmt = stmt.where(Chunk.slide_end >= slide_from)
        if slide_to:
            stmt = stmt.where(Chunk.slide_no <= slide_to)
        chunks = list(db.scalars(stmt.order_by(Chunk.slide_no)))
        existing = list(db.scalars(select(Question.stem).where(
            Question.document_id == document_id, Question.status == "accepted")))

    num_slides = sum((c.slide_end or c.slide_no) - c.slide_no + 1 for c in chunks)
    target = n or max(1, round(num_slides * cfg.questions_per_slide))
    state = BankState(document_id=document_id, session_no=doc.session_no, target=target, existing_stems=existing)
    seeds = select_seeds(chunks, target)
    sem = asyncio.Semaphore(cfg.concurrency)
    await asyncio.gather(*(process_seed(seed, sem, state) for seed in seeds))
    log.info("Document %s: mục tiêu %d, đạt %d, loại %d, lỗi %d",
             document_id, target, state.accepted, state.rejected, state.failed)
    if state.accepted == 0 and state.failed:
        return f"Không sinh được câu hỏi nào ({state.failed} lượt lỗi). Lỗi gần nhất: {state.last_error}"[:1000]
    return None


def run_generate_more(document_id: int, slide_from: int | None, slide_to: int | None, n: int | None) -> None:
    """Entry point cho BackgroundTasks của POST /documents/{id}/questions/generate."""
    from app.ingestion.pipeline import _set_status

    try:
        warning = asyncio.run(build_bank(document_id, slide_from, slide_to, n))
        _set_status(document_id, "ready", warning)
    except Exception as exc:
        log.exception("Sinh thêm câu hỏi lỗi cho document %s", document_id)
        _set_status(document_id, "ready", f"Sinh thêm câu hỏi lỗi: {exc}"[:1000])
