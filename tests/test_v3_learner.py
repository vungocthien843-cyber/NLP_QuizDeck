"""Kiểm thử tích hợp Mốc 2 (kế hoạch v3: C1–C3, D1, D3–D6) qua API thật trên Postgres.

Cần một Postgres đã chạy migrations 001–003 (pgvector có thể thay bằng TEXT khi thử). Bỏ qua nếu không có
biến môi trường TEST_DATABASE_URL. Ví dụ trong container:
  TEST_DATABASE_URL=$DATABASE_URL python -m pytest -q tests/test_v3_learner.py
CẢNH BÁO: test tạo và xoá dữ liệu có tiền tố "__test_v3__", không đụng dữ liệu khác.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")

PREFIX = "__test_v3__"
TYPES = ["dao_nhan_qua", "nham_khai_niem_lan_can", "sai_mot_chi_tiet"]


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from fastapi.testclient import TestClient
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.main import app
    from app.models import Attempt, Chunk, Document, MisconceptionStat, Question, Quiz, QuizQuestion, Response, User

    with SessionLocal() as db:
        doc = Document(filename=f"{PREFIX}.pdf", file_path="x", status="ready")
        db.add(doc)
        db.flush()
        chunk_ids = []
        for i in range(6):
            c = Chunk(document_id=doc.id, source_type="slide", raw_text=f"slide {i}", embed_text=f"slide {i}",
                      slide_no=i + 1)
            db.add(c)
            db.flush()
            chunk_ids.append(c.id)
        for i in range(30):           # 30 câu: 3 ý kiến thức, margin trải đều để chia được 3 mức khó
            concept = f"{PREFIX}ý {i % 3}"
            meta = {"A": {"role": "key"}}
            for j, letter in enumerate("BCD"):
                meta[letter] = {"role": "distractor", "source": "llm", "error_type": TYPES[(i + j) % 3]}
            db.add(Question(document_id=doc.id, stem=f"{PREFIX} câu {i}?",
                            options={"A": "đúng", "B": f"sai1 {i}", "C": f"sai2 {i}", "D": f"sai3 {i}"},
                            answer="A", rationales={}, source_chunk_ids=[chunk_ids[i % 6]], status="accepted",
                            bloom_level=["remember", "understand", "apply"][i % 3], pipeline_version="v2",
                            selection={"margin": i / 30}, option_meta=meta, concept=concept))
        db.commit()
        doc_id = doc.id
    # Gán thẳng mức khó cho câu thử (10 câu mỗi mức) thay vì gọi assign_levels: trên DB thật, assign_levels xếp hạng
    # câu thử chung với cả ngân hàng và ghi lại difficulty_est của câu thật. Cách chia mức có test riêng.
    with SessionLocal() as db:
        for i, q in enumerate(db.scalars(select(Question).where(Question.document_id == doc_id).order_by(Question.id))):
            q.difficulty_est = ("easy", "medium", "hard")[i % 3]
        db.commit()
    yield TestClient(app), doc_id
    with SessionLocal() as db:                         # dọn dữ liệu test
        qids = list(db.scalars(select(Question.id).where(Question.document_id == doc_id)))
        quiz_ids = list(db.scalars(select(QuizQuestion.quiz_id).where(QuizQuestion.question_id.in_(qids))))
        uids = list(db.scalars(select(User.id).where(User.code.like(f"{PREFIX}%"))))
        db.execute(delete(Response).where(Response.question_id.in_(qids)))
        db.execute(delete(Attempt).where(Attempt.quiz_id.in_(quiz_ids)))
        db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids)))
        db.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
        db.execute(delete(MisconceptionStat).where(MisconceptionStat.user_id.in_(uids)))
        db.execute(delete(User).where(User.id.in_(uids)))
        db.execute(delete(Question).where(Question.document_id == doc_id))
        db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        db.execute(delete(Document).where(Document.id == doc_id))
        db.commit()


def test_learner_flow(client):
    c, doc_id = client
    u = c.post("/users/login", json={"code": f"{PREFIX}SV01", "display_name": "Thử"}).json()
    assert c.post("/users/login", json={"code": f"{PREFIX}sv01"}).json()["user_id"] == u["user_id"]  # không phân biệt hoa thường

    # Đề theo mức khó: mọi câu đều đúng mức "hard" (đủ câu nên không bù)
    q = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10, "difficulty": "hard",
                                 "user_id": u["user_id"]}).json()
    assert q["difficulty"] == "hard" and q["mode"] == "difficulty" and q["notice"] is None
    from app.db import SessionLocal
    from app.models import Question
    with SessionLocal() as db:
        levels = {db.get(Question, x["question_id"]).difficulty_est for x in q["questions"]}
    assert levels == {"hard"}

    # Chưa có dữ liệu → luyện điểm yếu trả đề thường kèm thông báo
    w0 = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10, "mode": "weakness",
                                  "user_id": u["user_id"]}).json()
    assert w0["mode"] == "normal" and "Chưa đủ dữ liệu" in w0["notice"]

    # Làm đề thường: chọn B ở mọi câu (sai)
    quiz = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10}).json()
    answers = {str(x["question_id"]): "B" for x in quiz["questions"]}
    at = c.post("/attempts", json={"quiz_id": quiz["quiz_id"], "user_id": u["user_id"], "answers": answers}).json()
    assert at["num_correct"] == 0

    # Xem lại: mọi câu sai có chẩn đoán hiểu nhầm
    rv = c.get(f"/attempts/{at['attempt_id']}/review").json()
    assert all(it["misconception"] and it["misconception"]["chan_doan"] for it in rv["items"])

    # Hồ sơ có điểm yếu và thống kê theo loại lỗi
    prof = c.get(f"/users/{u['user_id']}/profile").json()
    assert prof["n_answered"] == 10 and prof["accuracy"] == 0.0
    assert prof["weaknesses"] and sum(prof["by_error_type"].values()) == 10
    top = prof["weaknesses"][0]

    # Luyện điểm yếu: câu đầu bảng phải thuộc ý kiến thức yếu nhất, có lý do
    w = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10, "mode": "weakness",
                                 "user_id": u["user_id"]}).json()
    assert w["mode"] == "weakness"
    from sqlalchemy import select
    from app.models import QuizQuestion
    with SessionLocal() as db:
        rows = db.execute(select(QuizQuestion.question_id, QuizQuestion.reason)
                          .where(QuizQuestion.quiz_id == w["quiz_id"])).all()
        concepts = [db.get(Question, qid).concept for qid, _ in rows]
    weak_concepts = {x["concept"] for x in prof["weaknesses"]}
    assert sum(cn in weak_concepts for cn in concepts) >= 8
    assert any(r and r.get("weak_concept") == top["concept"] for _, r in rows)

    # Trả lời đúng hết → điểm yếu giảm
    answers = {str(x["question_id"]): "A" for x in w["questions"]}
    c.post("/attempts", json={"quiz_id": w["quiz_id"], "user_id": u["user_id"], "answers": answers})
    prof2 = c.get(f"/users/{u['user_id']}/profile").json()
    before = {(x["concept"], x["error_type"]): x["score"] for x in prof["weaknesses"]}
    after = {(x["concept"], x["error_type"]): x["score"] for x in prof2["weaknesses"]}
    assert all(after.get(k, 0) < v for k, v in before.items())

    # Bài làm không đăng nhập vẫn chạy như cũ
    quiz2 = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10}).json()
    r = c.post("/attempts", json={"quiz_id": quiz2["quiz_id"], "user_name": "khách",
                                  "answers": {str(x["question_id"]): "A" for x in quiz2["questions"]}})
    assert r.status_code == 200 and r.json()["num_correct"] == 10
