"""Bước 1: đóng băng câu hỏi để mọi bước sau đọc cùng một dữ liệu, kể cả khi ngân hàng thay đổi.

Chỉ lấy tài liệu đang hoạt động và câu do pipeline hiện tại sinh. Câu của pipeline cũ (có bước LLM
groundedness trong validation) bị loại, vì kết quả của chúng không nói gì về hệ thống hiện tại.
Chạy: python -m eval.mcq.step1_snapshot [--force]
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.generation.common import word_count
from app.models import Chunk, Document, Question
from app.prompts import PROMPT_DIR
from eval.mcq.common import SNAPSHOT, SNAPSHOT_CHUNKS, SNAPSHOT_META, fail

PROMPT_FILES = ("mcq_system.txt", "mcq_user.txt", "mcq_bloom.json", "few_shot.json")


def _prompt_hash() -> str:
    digest = hashlib.sha256()
    for name in PROMPT_FILES:
        digest.update((PROMPT_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


def duplicate_pairs(questions: list[Question], threshold: float) -> dict:
    """Đếm cặp câu accepted trong cùng tài liệu có cosine vượt ngưỡng."""
    by_doc: dict[int, list[Question]] = {}
    for q in questions:
        if q.status == "accepted" and q.stem_embedding is not None:
            by_doc.setdefault(q.document_id, []).append(q)
    total, over, max_sim = 0, 0, 0.0
    for group in by_doc.values():
        if len(group) < 2:
            continue
        vectors = np.array([q.stem_embedding for q in group], dtype=float)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        upper = (vectors @ vectors.T)[np.triu_indices(len(group), k=1)]
        total += upper.size
        over += int((upper > threshold).sum())
        max_sim = max(max_sim, float(upper.max()))
    return {"pairs": total, "over_threshold": over, "threshold": threshold, "max_similarity": round(max_sim, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Ghi đè snapshot cũ")
    args = parser.parse_args()
    if SNAPSHOT.exists() and not args.force:
        fail(f"{SNAPSHOT.name} đã có. Tạo lại sẽ làm phiếu chấm cũ không còn khớp; thêm --force nếu chắc chắn.")

    cfg = get_config()
    with SessionLocal() as db:
        documents = list(db.scalars(select(Document).where(Document.is_active).order_by(Document.id)))
        doc_ids = [d.id for d in documents]
        chunks = list(db.scalars(select(Chunk).where(Chunk.document_id.in_(doc_ids), Chunk.is_active)))
        all_questions = list(db.scalars(select(Question).where(Question.document_id.in_(doc_ids)).order_by(Question.id)))

    questions = [q for q in all_questions if "groundedness" not in (q.validation or {})]
    if not questions:
        fail("không có câu hỏi nào của pipeline hiện tại trong các tài liệu đang hoạt động.")

    with SNAPSHOT.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps({
                "id": q.id, "document_id": q.document_id, "session_no": q.session_no, "stem": q.stem,
                "options": q.options, "answer": q.answer, "rationales": q.rationales, "explanation": q.explanation,
                "bloom_level": q.bloom_level, "source_chunk_ids": q.source_chunk_ids, "status": q.status,
                "validation": q.validation,
            }, ensure_ascii=False) + "\n")

    with SNAPSHOT_CHUNKS.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({
                "id": c.id, "document_id": c.document_id, "slide_no": c.slide_no, "slide_end": c.slide_end,
                "title": c.title, "embed_text": c.embed_text, "words": word_count(c),
            }, ensure_ascii=False) + "\n")

    slides = {d.id: 0 for d in documents}
    for c in chunks:
        slides[c.document_id] += (c.slide_end or c.slide_no) - c.slide_no + 1
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": cfg.models.mcq_generator,
        "prompt_hash": _prompt_hash(),
        "bank": cfg.bank.model_dump(),
        "documents": [{"id": d.id, "filename": d.filename, "status": d.status, "num_slides": slides[d.id]}
                      for d in documents],
        "excluded_old_pipeline": len(all_questions) - len(questions),
        "duplicates": duplicate_pairs(questions, cfg.bank.dedup_threshold),
    }
    SNAPSHOT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    accepted = sum(q.status == "accepted" for q in questions)
    print(f"Tài liệu: {len(documents)} ({', '.join(d.filename for d in documents)})")
    print(f"Câu hỏi: {len(questions)} ({accepted} accepted, {len(questions) - accepted} rejected)")
    print(f"Đã bỏ {meta['excluded_old_pipeline']} câu của pipeline cũ")
    print(f"Đã ghi: {SNAPSHOT}")


if __name__ == "__main__":
    main()
