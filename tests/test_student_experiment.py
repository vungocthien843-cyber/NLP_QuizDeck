"""Kiểm thử tích hợp thử nghiệm sinh viên (Mốc 3, G4/G5): chuẩn bị → 6 sinh viên làm đủ 3 bước qua API → phân tích.

Cần Postgres đã chạy migrations 001–004 (TEST_DATABASE_URL), giống test_v3_learner.py. Dữ liệu thử có tiền tố
"__test_g4__" và được xoá sau khi chạy; cấu hình thử nghiệm ghi vào thư mục tạm (không đụng thử nghiệm thật).
"""
import json
import os
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")

PREFIX = "__test_g4__"
TYPES = ["dao_nhan_qua", "nham_khai_niem_lan_can", "sai_mot_chi_tiet"]
N_SLIDES = 6


def _fake_embed(texts):
    rng = np.random.default_rng(len(texts))
    v = rng.normal(size=(len(texts), 8))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("EXPERIMENT_CONFIG", str(tmp_path / "data" / "thu_nghiem.json"))
    monkeypatch.setenv("STUDENT_EXP_DIR", str(tmp_path))
    import importlib

    import eval.student.common
    importlib.reload(eval.student.common)
    for m in ("eval.student.chuan_bi", "eval.student.phan_tich"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    import app.learner.difficulty as diff
    monkeypatch.setattr(diff, "_default_embed", _fake_embed)
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import (Attempt, Chunk, Document, Feedback, MisconceptionStat, Question, Quiz, QuizQuestion,
                            Response, User)
    with SessionLocal() as db:
        doc = Document(filename=f"{PREFIX}.pdf", file_path="x", status="ready")
        db.add(doc)
        db.flush()
        chunks = []
        for i in range(N_SLIDES):
            c = Chunk(document_id=doc.id, source_type="slide", raw_text=f"slide {i}", embed_text=f"slide {i}",
                      slide_no=i + 1)
            db.add(c)
            db.flush()
            chunks.append(c.id)
        for i in range(24):        # ngân hàng: 4 câu mỗi slide, để luyện tập có câu nhắm đúng slide
            meta = {"A": {"role": "key"}, **{L: {"role": "distractor", "source": "llm", "error_type": TYPES[(i + j) % 3]}
                                             for j, L in enumerate("BCD")}}
            db.add(Question(document_id=doc.id, stem=f"{PREFIX} ngân hàng {i}?", options={"A": "đúng", "B": f"b{i}",
                            "C": f"c{i}", "D": f"d{i}"}, answer="A", rationales={}, source_chunk_ids=[chunks[i % 6]],
                            status="accepted", bloom_level="understand", option_meta=meta, concept=f"{PREFIX}kp{i}",
                            selection={"mean_cos_dk": 0.5 + i / 100}, difficulty_est="medium"))
        db.commit()
        doc_id = doc.id
    res = tmp_path / "G1"
    res.mkdir()
    for cfg in ("C0", "C5"):
        with (res / f"questions_{cfg}.jsonl").open("w", encoding="utf-8") as f:
            for i, c in enumerate(chunks):
                d = [f"{cfg} sai {i}-{j}" for j in range(3)]
                v2 = {"picked": [{"text": t, "source": "llm", "error_type": TYPES[j]} for j, t in enumerate(d)],
                      "selection": {"margin": 0.1 * i}, "answer_type": "dinh_nghia"} if cfg == "C5" else None
                f.write(json.dumps({"question": {"stem": f"{PREFIX} {cfg} câu {i}?", "answer": f"đúng {i}",
                                                 "distractors": d, "evidence": f"ev {i}", "context": "ctx",
                                                 "key_point": f"{PREFIX}ý {i}", "explanation": "vì vậy",
                                                 "source_chunk_ids": [c], "rationales": {}},
                                    "meta": {"seed_chunk": c, "bloom": "understand", "passed": True, "v2": v2}},
                                   ensure_ascii=False) + "\n")
    codes = tmp_path / "ma.txt"
    codes.write_text("\n".join(f"{PREFIX}sv{i}" for i in range(6)), encoding="utf-8")
    yield res, codes, doc_id
    with SessionLocal() as db:
        uids = list(db.scalars(select(User.id).where(User.code.like(f"{PREFIX}%"))))
        qids = list(db.scalars(select(Question.id).where(Question.document_id == doc_id)))
        quiz_ids = list(db.scalars(select(QuizQuestion.quiz_id).where(QuizQuestion.question_id.in_(qids))))
        db.execute(delete(Feedback).where(Feedback.user_id.in_(uids)))
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


def _answer(quiz, wrong_ratio, rng, keys):
    out = {}
    for q in quiz["questions"]:
        key = keys[q["question_id"]]
        out[str(q["question_id"])] = (rng.choice([L for L in "ABCD" if L != key]) if rng.random() < wrong_ratio else key)
    return out


def test_experiment_end_to_end(env, monkeypatch):
    import random

    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app
    from app.models import Question, Quiz
    from eval.student import chuan_bi, common, phan_tich

    res, codes, doc_id = env
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(res), "--n", str(N_SLIDES), "--codes", str(codes),
                                      "--no-tag", "--practice-n", "6"])
    chuan_bi.main()
    cfg = json.loads(open(os.environ["EXPERIMENT_CONFIG"], encoding="utf-8").read())
    items = common.read_csv(common.ITEMS)
    assert len(items) == 2 * N_SLIDES
    for k in ("1", "2"):                                   # mỗi đề trộn V1/V3 và đủ mọi slide
        rows = [r for r in items if r["de"] == k]
        assert {r["phien_ban"] for r in rows} == {"V1", "V3"} and len({r["slide"] for r in rows}) == N_SLIDES
    with SessionLocal() as db:
        qs = [db.get(Question, int(r["question_id"])) for r in items]
        assert all(q.status == "experiment" and q.difficulty_est for q in qs)
        keys = {q.id: q.answer for q in qs}
    # câu thử nghiệm không lọt vào đề ngẫu nhiên
    c = TestClient(app)
    rnd = c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 20}).json()
    assert not set(keys) & {q["question_id"] for q in rnd["questions"]}

    rng = random.Random(0)
    for i, code in enumerate(cfg["members"]):
        u = c.post("/users/login", json={"code": code}).json()
        st = c.get("/experiment/state", params={"user_id": u["user_id"]}).json()
        assert st["member"] and st["step"] == "1"
        assert c.post("/experiment/practice", json={"user_id": u["user_id"]}).status_code == 409
        q1 = c.get(f"/quizzes/{cfg['quiz1_id']}").json()
        a1 = c.post("/attempts", json={"quiz_id": q1["quiz_id"], "user_id": u["user_id"],
                                       "answers": _answer(q1, 0.7, rng, keys)}).json()
        rv = c.get(f"/attempts/{a1['attempt_id']}/review").json()
        wrong = [it for it in rv["items"] if not it["is_correct"]]
        for it in wrong[:2]:
            assert c.post("/feedback", json={"user_id": u["user_id"], "attempt_id": a1["attempt_id"],
                                             "question_id": it["question_id"], "kind": "diag_item",
                                             "value": rng.choice([0, 1, 2])}).status_code == 204
        for kind in ("diag_overall", "explain_overall"):
            c.post("/feedback", json={"user_id": u["user_id"], "attempt_id": a1["attempt_id"], "kind": kind, "value": 4})
        c.post("/feedback", json={"user_id": u["user_id"], "attempt_id": a1["attempt_id"], "kind": "diag_overall",
                                  "value": 5})                       # gửi lại: ghi đè
        assert c.post("/feedback", json={"user_id": u["user_id"], "attempt_id": a1["attempt_id"], "kind": "diag_overall",
                                         "value": 9}).status_code == 400
        st = c.get("/experiment/state", params={"user_id": u["user_id"]}).json()
        assert st["step"] == "2" and "diag_overall" in st["feedback_kinds"][str(a1["attempt_id"])]
        # một đề tự tạo ngoài thử nghiệm không được tính là đã luyện tập
        c.post("/quizzes", json={"scope": {"document_ids": [doc_id]}, "n": 10, "user_id": u["user_id"]})
        p = c.post("/experiment/practice", json={"user_id": u["user_id"]}).json()
        assert c.post("/experiment/practice", json={"user_id": u["user_id"]}).json()["quiz_id"] == p["quiz_id"]
        assert p["notice"] is None
        assert c.get("/experiment/state", params={"user_id": u["user_id"]}).json()["practice_quiz_id"] == p["quiz_id"]
        with SessionLocal() as db:
            pk = {x["question_id"]: db.get(Question, x["question_id"]).answer for x in p["questions"]}
            mode = db.get(Quiz, p["quiz_id"]).mode
        assert mode == ("weakness" if cfg["members"][code] == "A" else "normal")
        a2 = c.post("/attempts", json={"quiz_id": p["quiz_id"], "user_id": u["user_id"],
                                       "answers": _answer(p, 0.3, rng, pk)}).json()
        c.post("/feedback", json={"user_id": u["user_id"], "attempt_id": a2["attempt_id"], "kind": "practice_useful",
                                  "value": 3 + i % 3})
        assert c.get("/experiment/state", params={"user_id": u["user_id"]}).json()["step"] == "3"
        q2 = c.get(f"/quizzes/{cfg['quiz2_id']}").json()
        c.post("/attempts", json={"quiz_id": q2["quiz_id"], "user_id": u["user_id"],
                                  "answers": _answer(q2, 0.4, rng, keys)})
        assert c.get("/experiment/state", params={"user_id": u["user_id"]}).json()["step"] == "done"
    outsider = c.post("/users/login", json={"code": f"{PREFIX}nguoi_ngoai"}).json()
    assert c.get("/experiment/state", params={"user_id": outsider["user_id"]}).json()["member"] is False

    monkeypatch.setattr(sys, "argv", ["x"])
    phan_tich.main()
    rep = (common.RESULTS / "bao_cao_sinh_vien.md").read_text(encoding="utf-8")
    assert "V1 và V3 theo cặp cùng slide" in rep and "Hoàn thành đủ 3 bước: nhóm A 3, nhóm B 3" in rep
    assert len(common.read_csv(common.RESULTS / "phan_tich_cau.csv")) == 2 * N_SLIDES

    monkeypatch.setattr(sys, "argv", ["x", "--close"])   # đóng thử nghiệm → API báo không còn thử nghiệm
    chuan_bi.main()
    assert c.get("/experiment/state", params={"user_id": outsider["user_id"]}).json()["active"] is False
