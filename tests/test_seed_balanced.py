"""Chọn hạt giống cho bộ đánh giá: chia đều theo bài, bỏ slide tiêu đề và slide hành chính (sửa lỗi G1: chương 9
chỉ được 2/100 hạt giống vì pick_seeds cắt seeds[:n] sau khi rải theo thứ tự bài). Cần TEST_DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")
PREFIX = "__test_seed__"


@pytest.fixture()
def docs():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models import Chunk, Document
    body = " ".join(["mô hình ngôn ngữ thống kê dự đoán từ tiếp theo dựa trên xác suất"] * 6)
    ids = []
    with SessionLocal() as db:
        for k, n_slides in enumerate((30, 12, 40)):
            d = Document(filename=f"{PREFIX}Slide_Chuong{k + 1}.pdf", file_path="x", status="ready")
            db.add(d)
            db.flush()
            ids.append(d.id)
            for s in range(1, n_slides + 1):
                text = {1: f"Chương {k + 1} tiêu đề " + body, 2: "Lộ trình bài học " + body,
                        n_slides: "Cảm ơn " + body}.get(s, f"slide {s} " + body)
                db.add(Chunk(document_id=d.id, source_type="slide", raw_text=text, embed_text=text, slide_no=s))
        db.commit()
    yield ids
    with SessionLocal() as db:
        db.execute(delete(Chunk).where(Chunk.document_id.in_(ids)))
        db.execute(delete(Document).where(Document.id.in_(ids)))
        db.commit()


def test_balanced_seeds_cover_every_document(docs):
    from eval.v2 import run_ablation as ra

    assert ra.resolve_docs(f"{PREFIX}Slide_Chuong") == docs
    seeds = ra.pick_seeds_balanced(docs, 10, 42)
    by_doc = {d: [s for s in seeds if s.chunk.document_id == d] for d in docs}
    assert len(by_doc[docs[0]]) == 10 and len(by_doc[docs[2]]) == 10        # đều 10 / bài, kể cả bài cuối
    assert len(by_doc[docs[1]]) == 9          # bài 12 slide: bỏ tiêu đề + lộ trình + cảm ơn → chỉ còn 9 đủ điều kiện
    assert all(s.chunk.slide_no > 1 for s in seeds)                         # bỏ slide tiêu đề
    assert not any(s.chunk.raw_text.startswith(("Lộ trình", "Cảm ơn")) for s in seeds)   # bỏ slide hành chính
    assert {s.bloom_level for s in seeds} == {"remember", "understand", "apply"}
    spread = sorted(s.chunk.slide_no for s in by_doc[docs[2]])
    assert spread[-1] - spread[0] > 25                                      # rải đều cả bài, không dồn đầu bài
    with pytest.raises(SystemExit):
        ra.resolve_docs("__khong_co_bai_nay__")
