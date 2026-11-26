"""Điền option_meta cho câu hỏi ĐÃ CÓ trong ngân hàng (kế hoạch v3, việc B6), để câu cũ dùng được cho chẩn đoán
hiểu nhầm mà không phải sinh lại.

  câu v2  khớp text 3 phương án sai với distractor_candidates (selected) → source, error_type, candidate_id
  câu v1  không có ứng viên → source "v1"
Phương án sai chưa có loại hiểu nhầm (ViT5, v1) được gắn nhãn bằng candidates.tag_misconceptions (1 lần gọi LLM mỗi
câu). Nhãn mới của ứng viên v2 cũng được ghi lại vào distractor_candidates.error_type.

Cần chạy migration 003 và build lại image trước. Chạy trong container API:
  python -m app.maintenance.backfill_option_meta --dry-run            # chỉ đếm, không ghi, không gọi LLM
  python -m app.maintenance.backfill_option_meta --limit 5            # thử 5 câu
  python -m app.maintenance.backfill_option_meta                       # toàn bộ câu accepted chưa có option_meta
  python -m app.maintenance.backfill_option_meta --no-tag              # chỉ khớp ứng viên, không gọi LLM
"""
import argparse
import asyncio
import logging
from collections import Counter

from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.generation.candidates import Candidate, tag_misconceptions
from app.generation.common import format_context
from app.models import Chunk, DistractorCandidate, Question

log = logging.getLogger(__name__)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def match_meta(q: Question, cands: list[DistractorCandidate]) -> dict[str, dict]:
    """option_meta từ dữ liệu sẵn có, chưa gọi LLM. Câu v2: ưu tiên ứng viên selected, khớp theo text chuẩn hoá."""
    pool = {_norm(c.text): c for c in sorted(cands, key=lambda c: not c.selected)[::-1]}
    meta: dict[str, dict] = {}
    for letter, text in q.options.items():
        if letter == q.answer:
            meta[letter] = {"role": "key"}
            continue
        c = pool.get(_norm(text))
        if c is not None:
            meta[letter] = {"role": "distractor", "source": c.source, "error_type": c.error_type, "candidate_id": c.id}
        else:
            meta[letter] = {"role": "distractor", "source": "v1" if q.pipeline_version == "v1" else "unknown",
                            "error_type": None, "candidate_id": None}
    return meta


async def tag_question(q: Question, meta: dict[str, dict], chunks: list[Chunk], sem: asyncio.Semaphore) -> int:
    """Gắn nhãn cho các phương án sai còn thiếu error_type. Trả số nhãn đã gắn."""
    missing = [letter for letter, m in meta.items() if m["role"] == "distractor" and not m.get("error_type")]
    if not missing:
        return 0
    cands = [Candidate(q.options[letter], meta[letter]["source"]) for letter in missing]
    key_point = q.concept or (q.validation or {}).get("key_point") or ""
    async with sem:
        stats = await tag_misconceptions(format_context(chunks), q.stem, q.options[q.answer], key_point, cands)
    if stats.get("error"):
        log.warning("Câu %s: gắn nhãn lỗi: %s", q.id, stats["error"])
    for letter, c in zip(missing, cands, strict=True):
        meta[letter]["error_type"] = c.error_type
    return sum(1 for c in cands if c.error_type)


async def run(a) -> None:
    with SessionLocal() as db:
        stmt = select(Question).where(Question.status == "accepted", Question.option_meta.is_(None))
        if a.docs:
            stmt = stmt.where(Question.document_id.in_(a.docs))
        qs = list(db.scalars(stmt.order_by(Question.id)))
        if a.limit:
            qs = qs[:a.limit]
        cands_by_q: dict[int, list[DistractorCandidate]] = {}
        for c in db.scalars(select(DistractorCandidate).where(DistractorCandidate.question_id.in_([q.id for q in qs]))):
            cands_by_q.setdefault(c.question_id, []).append(c)
        chunk_ids = {cid for q in qs for cid in q.source_chunk_ids}
        chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))}

    metas = {q.id: match_meta(q, cands_by_q.get(q.id, [])) for q in qs}
    stats = Counter()
    for q in qs:
        stats[f"câu {q.pipeline_version}"] += 1
        for m in metas[q.id].values():
            if m["role"] == "distractor":
                stats["phương án sai"] += 1
                stats["đã có loại lỗi" if m.get("error_type") else "thiếu loại lỗi"] += 1
                stats["khớp được ứng viên" if m.get("candidate_id") else "không khớp ứng viên"] += 1
    print(f"{len(qs)} câu accepted chưa có option_meta: {dict(stats)}")
    if a.dry_run:
        print("--dry-run: không ghi gì.")
        return

    if not a.no_tag:
        sem = asyncio.Semaphore(get_config().bank.concurrency)
        tagged = await asyncio.gather(*(tag_question(q, metas[q.id], [chunks[c] for c in q.source_chunk_ids if c in chunks],
                                                     sem) for q in qs))
        print(f"Đã gắn {sum(tagged)} nhãn hiểu nhầm.")

    with SessionLocal() as db:
        for q in qs:
            row = db.get(Question, q.id)
            row.option_meta = metas[q.id]
            if not row.concept:
                row.concept = (row.validation or {}).get("key_point") or None
            for m in metas[q.id].values():          # nhãn mới của ứng viên v2 (thường là ViT5) ghi lại vào bảng ứng viên
                if m.get("candidate_id") and m.get("error_type"):
                    c = db.get(DistractorCandidate, m["candidate_id"])
                    if c is not None and not c.error_type:
                        c.error_type = m["error_type"]
        db.commit()
    print(f"Đã ghi option_meta cho {len(qs)} câu.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm, không ghi DB, không gọi LLM")
    ap.add_argument("--no-tag", action="store_true", help="không gọi LLM gắn nhãn phương án thiếu loại lỗi")
    ap.add_argument("--docs", nargs="*", type=int, help="chỉ các bài này")
    ap.add_argument("--limit", type=int, help="chỉ N câu đầu")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
