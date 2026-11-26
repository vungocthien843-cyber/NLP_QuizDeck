"""Dò sẵn slide chứa câu trích dẫn cho mọi câu accepted và lưu vào validation.evidence_slide_no, để màn hình xem
lại không phải mở PDF lúc người học chờ (đọc PDF qua bind mount Windows ↔ Docker rất chậm). Không gọi LLM.
  python -m app.maintenance.locate_evidence
"""
import time

from sqlalchemy import select

from app.api.attempts import _evidence
from app.db import SessionLocal
from app.models import Chunk, Document, Question

if __name__ == "__main__":
    t0 = time.perf_counter()
    with SessionLocal() as db:
        qs = [q for q in db.scalars(select(Question).where(Question.status == "accepted"))
              if (q.validation or {}).get("evidence_text") and "evidence_slide_no" not in (q.validation or {})]
        chunk_ids = {cid for q in qs for cid in q.source_chunk_ids}
        for q in qs:
            ev = (q.validation or {}).get("evidence")
            if isinstance(ev, dict) and (ev.get("details") or {}).get("chunk_id"):
                chunk_ids.add(ev["details"]["chunk_id"])
        chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))}
        docs = {d.id: d for d in db.scalars(select(Document))}
        for i, q in enumerate(qs, 1):
            _evidence(q, chunks, docs)
            if i % 50 == 0:
                db.commit()
                print(f"  {i}/{len(qs)} câu")
        db.commit()
    print(f"Đã dò slide trích dẫn cho {len(qs)} câu trong {time.perf_counter() - t0:.1f} s")
