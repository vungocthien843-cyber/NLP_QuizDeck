"""Kiểm thử phân quyền tài liệu (Đợt 0): thư viện chung, slide riêng của sinh viên, hạn mức, trợ lý không lộ
slide riêng. Chạy trên Postgres thật đã có migrations 001–006 (TEST_DATABASE_URL), giống test_auth.py.
Dữ liệu thử có tiền tố "__acc__", được xóa khi xong.
"""
import io
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")

P = "__acc__"
BASE = "http://testserver"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    os.environ.update({"PUBLIC_BASE_URL": BASE, "SESSION_SECRET": "x" * 40, "COOKIE_SECURE": "false",
                       "AUTH_REQUIRED": "true", "STUDENT_MAX_DOCS": "2", "STUDENT_MAX_PROCESSING": "1",
                       "DATA_DIR": str(tmp_path_factory.mktemp("data"))})
    from sqlalchemy import delete, select

    from app import api
    from app.auth.sessions import create_session
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import (Attempt, AuthSession, ChatMessage, Chunk, Conversation, Document, Question, Quiz,
                            QuizQuestion, Response, User)
    get_settings.cache_clear()
    get_settings().upload_dir.mkdir(parents=True, exist_ok=True)
    import app.api.documents as docs_api
    docs_api.run_pipeline = lambda doc_id: None          # không chạy pipeline thật (cần mô hình)

    ids = {}
    with SessionLocal() as db:
        for name, admin in (("gv", True), ("a", False), ("b", False)):
            u = User(code=f"{name}{P}@ictu.edu.vn", email=f"{name}{P}@ictu.edu.vn", is_admin=admin)
            db.add(u)
            db.flush()
            ids[name] = u.id
        for key, owner, shared in (("shared", "gv", True), ("a_priv", "a", False), ("b_priv", "b", False)):
            d = Document(filename=f"{P}{key}.pdf", file_path="x", status="ready", owner_user_id=ids[owner],
                         is_shared=shared)
            db.add(d)
            db.flush()
            ids[key] = d.id
            c = Chunk(document_id=d.id, source_type="slide", raw_text=f"{key} nội dung", embed_text=key, slide_no=1)
            db.add(c)
            db.flush()
            for i in range(6):
                db.add(Question(document_id=d.id, stem=f"{P}{key} câu {i}?", options={"A": "1", "B": "2", "C": "3",
                                "D": "4"}, answer="A", rationales={}, source_chunk_ids=[c.id], status="accepted",
                                bloom_level="remember", pipeline_version="v2", difficulty_est="easy"))
            ids[key + "_chunk"] = c.id
        db.commit()
        tokens = {n: create_session(db, db.get(User, ids[n]), "pytest", "127.0.0.1") for n in ("gv", "a", "b")}

    from fastapi.testclient import TestClient
    from app.main import app

    def client(name):
        tok, sess = tokens[name]
        c = TestClient(app, base_url=BASE)
        c.cookies.set("rq_session", tok)
        c.headers["X-CSRF-Token"] = sess.csrf_token
        return c

    yield {"ids": ids, "client": client, "docs_api": docs_api}

    with SessionLocal() as db:
        doc_ids = list(db.scalars(select(Document.id).where(Document.filename.like(f"%{P}%"))))
        uids = [ids["gv"], ids["a"], ids["b"]]
        qids = list(db.scalars(select(Question.id).where(Question.document_id.in_(doc_ids))))
        quiz_ids = list(db.scalars(select(Quiz.id).where(Quiz.user_id.in_(uids))))
        db.execute(delete(Response).where(Response.question_id.in_(qids)))
        db.execute(delete(Attempt).where(Attempt.quiz_id.in_(quiz_ids)))
        db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids)))
        db.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
        conv_ids = list(db.scalars(select(Conversation.id).where(Conversation.user_id.in_(uids))))
        db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
        db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
        db.execute(delete(Question).where(Question.document_id.in_(doc_ids)))
        db.execute(delete(Chunk).where(Chunk.document_id.in_(doc_ids)))
        db.execute(delete(Document).where(Document.id.in_(doc_ids)))
        db.execute(delete(AuthSession).where(AuthSession.user_id.in_(uids)))
        db.execute(delete(User).where(User.id.in_(uids)))
        db.commit()
    for k in ("AUTH_REQUIRED", "STUDENT_MAX_DOCS", "STUDENT_MAX_PROCESSING", "DATA_DIR"):
        os.environ.pop(k, None)
    get_settings.cache_clear()


def _mine(c):
    return {d["id"]: d for d in c.get("/documents").json()}


def test_list_visibility(env):
    i = env["ids"]
    a, b, gv = env["client"]("a"), env["client"]("b"), env["client"]("gv")
    da, db_, dg = _mine(a), _mine(b), _mine(gv)
    assert i["shared"] in da and i["a_priv"] in da and i["b_priv"] not in da
    assert i["shared"] in db_ and i["b_priv"] in db_ and i["a_priv"] not in db_
    assert {i["shared"], i["a_priv"], i["b_priv"]} <= set(dg)                      # quản trị viên thấy hết
    assert da[i["a_priv"]]["is_mine"] and da[i["a_priv"]]["can_edit"] and not da[i["a_priv"]]["is_shared"]
    assert not da[i["shared"]]["can_edit"]                                          # sinh viên không sửa bài chung


def test_cannot_read_others_private(env):
    i, b = env["ids"], env["client"]("b")
    assert b.get(f"/documents/{i['a_priv']}").status_code == 404
    assert b.get(f"/documents/{i['a_priv']}/slides").status_code == 404
    assert b.get(f"/documents/{i['a_priv']}/slides/1/image").status_code == 404
    assert b.get(f"/chunks/{i['a_priv_chunk']}/image").status_code == 404
    assert b.delete(f"/documents/{i['a_priv']}").status_code == 404
    assert b.post(f"/documents/{i['a_priv']}/questions/generate", json={}).status_code == 404
    assert b.get(f"/documents/{i['shared']}").status_code == 200


def test_student_cannot_modify_shared(env):
    i, a = env["ids"], env["client"]("a")
    assert a.delete(f"/documents/{i['shared']}").status_code == 403
    assert a.patch(f"/documents/{i['a_priv']}", json={"is_shared": True}).status_code == 403
    r = a.patch(f"/documents/{i['a_priv']}", json={"session_no": 7})
    assert r.status_code == 200 and r.json()["session_no"] == 7


def test_quiz_scope_restricted(env):
    i, a = env["ids"], env["client"]("a")
    assert a.post("/quizzes", json={"scope": {"document_ids": [i["b_priv"]]}, "n": 10}).status_code == 404
    r = a.post("/quizzes", json={"scope": {}, "n": 50})
    assert r.status_code == 200, r.text
    stems = [q["stem"] for q in r.json()["questions"]]
    assert stems and not any("b_priv" in s for s in stems)                          # không lấy câu từ slide riêng của B
    quiz_id = r.json()["quiz_id"]
    assert env["client"]("b").get(f"/quizzes/{quiz_id}").status_code == 404         # B không mở được đề của A
    assert a.get(f"/quizzes/{quiz_id}").status_code == 200


def test_scope_helper_empty_means_nothing(env):
    from app.auth.access import NO_DOC, restrict_scope
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        ghost = User(id=-999, is_admin=False)
        s = restrict_scope(db, ghost, None)
        assert s.document_ids and NO_DOC not in s.document_ids        # vẫn thấy thư viện chung
        assert restrict_scope(db, None, None).document_ids is None    # chế độ cũ: không giới hạn


def test_chat_restricted(env, monkeypatch):
    import app.api.chat as chat_api
    seen = {}

    async def fake_stream(conv_id, message, question_id, attempt_id, allowed):
        seen["allowed"] = allowed
        yield '{"type":"done","citations":[]}\n'

    monkeypatch.setattr(chat_api, "answer_stream", fake_stream)
    i = env["ids"]
    a, b = env["client"]("a"), env["client"]("b")
    r = a.post("/chat", json={"message": "xin chào"})
    assert r.status_code == 200
    assert i["shared"] in seen["allowed"] and i["a_priv"] in seen["allowed"] and i["b_priv"] not in seen["allowed"]
    conv = int(r.headers["X-Conversation-Id"])
    assert b.post("/chat", json={"message": "đọc trộm", "conversation_id": conv}).status_code == 404
    from app.db import SessionLocal
    from app.models import Question
    with SessionLocal() as db:
        qb = db.query(Question).filter(Question.document_id == i["b_priv"]).first().id
    assert a.post("/chat", json={"message": "giải thích", "question_id": qb}).status_code == 404


def test_upload_quota(env):
    a = env["client"]("a")
    q = a.get("/documents/quota").json()
    assert q == {"unlimited": False, "max_docs": 2, "used_docs": 1, "max_upload_mb": q["max_upload_mb"]}
    f = lambda n: {"file": (f"{P}{n}.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}  # noqa: E731
    r = a.post("/documents", files=f("up1"))
    assert r.status_code == 200 and r.json()["is_shared"] is False and r.json()["is_mine"]
    # bài vừa tải đang ở trạng thái "uploaded" (đang xử lý) → hết hạn mức số bài (2) trước
    r2 = a.post("/documents", files=f("up2"))
    assert r2.status_code == 429
    gv = env["client"]("gv")
    r3 = gv.post("/documents", files=f("gv1"))
    assert r3.status_code == 200 and r3.json()["is_shared"] is True             # quản trị viên → thư viện chung
    assert gv.get("/documents/quota").json()["unlimited"] is True


def test_busy_limit(env):
    b = env["client"]("b")
    f = {"file": (f"{P}bb.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    assert b.post("/documents", files=f).status_code == 200                     # 1 đang xử lý
    from app.db import SessionLocal
    from app.models import Document
    with SessionLocal() as db:                                                 # dọn bớt để không vướng hạn mức số bài
        db.query(Document).filter(Document.id == env["ids"]["b_priv"]).update({"is_active": False})
        db.commit()
    r = b.post("/documents", files={"file": (f"{P}bc.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert r.status_code == 429 and "chưa xử lý xong" in r.json()["detail"]


def test_admin_can_share(env):
    i, gv = env["ids"], env["client"]("gv")
    r = gv.patch(f"/documents/{i['a_priv']}", json={"is_shared": True})
    assert r.status_code == 200 and r.json()["is_shared"] is True
    assert env["client"]("b").get(f"/documents/{i['a_priv']}").status_code == 200   # giờ B cũng thấy


def test_submit_unanswered_on_timeout(env):
    a = env["client"]("a")
    quiz = a.post("/quizzes", json={"scope": {}, "n": 10}).json()
    first = quiz["questions"][0]["question_id"]
    assert a.post("/attempts", json={"quiz_id": quiz["quiz_id"], "answers": {first: "A"}}).status_code == 400
    r = a.post("/attempts", json={"quiz_id": quiz["quiz_id"], "answers": {first: "A"}, "allow_unanswered": True})
    assert r.status_code == 200 and r.json()["num_questions"] == 10
    items = a.get(f"/attempts/{r.json()['attempt_id']}/review").json()["items"]
    assert sum(i["chosen"] is None for i in items) == 9 and all(not i["is_correct"] for i in items if i["chosen"] is None)
    assert env["client"]("b").get(f"/attempts/{r.json()['attempt_id']}/review").status_code == 404


def test_conversations_and_history(env, monkeypatch):
    import app.api.chat as chat_api

    async def fake_stream(conv_id, message, question_id, attempt_id, allowed):
        yield '{"type":"done","citations":[]}\n'

    monkeypatch.setattr(chat_api, "answer_stream", fake_stream)
    from app.db import SessionLocal
    from app.models import ChatMessage
    i = env["ids"]
    a, b = env["client"]("a"), env["client"]("b")
    conv = int(a.post("/chat", json={"message": "Lan truyền ngược là gì?"}).headers["X-Conversation-Id"])
    with SessionLocal() as db:           # giả lập lượt trả lời đã lưu, có trích dẫn [1]
        db.add_all([ChatMessage(conversation_id=conv, role="user", content="Lan truyền ngược là gì?"),
                    ChatMessage(conversation_id=conv, role="assistant", content="Dùng quy tắc chuỗi [1].",
                                cited_chunk_ids=[i["shared_chunk"]])])
        db.commit()
    lst = a.get("/chat/conversations").json()
    assert lst and lst[0]["conversation_id"] == conv and lst[0]["title"].startswith("Lan truyền")
    assert all(c["conversation_id"] != conv for c in b.get("/chat/conversations").json())
    msgs = a.get(f"/chat/conversations/{conv}").json()
    assert msgs[-1]["citations"][0]["n"] == 1 and msgs[-1]["citations"][0]["document_id"] == i["shared"]
    assert b.get(f"/chat/conversations/{conv}").status_code == 404
    hist = a.get("/users/me/attempts").json()
    assert hist and {"attempt_id", "score_10", "label", "num_correct"} <= set(hist[0])
    assert all(h["attempt_id"] not in {x["attempt_id"] for x in b.get("/users/me/attempts").json()} for h in hist)


def test_admin_api(env, monkeypatch):
    import app.api.admin as admin_api
    monkeypatch.setattr(admin_api, "run_pipeline", lambda doc_id: None)
    from app.db import SessionLocal
    from app.models import Document, Question
    i, a, gv = env["ids"], env["client"]("a"), env["client"]("gv")
    for path in ("/admin/stats", "/admin/users", f"/admin/documents/{i['shared']}/questions"):
        assert a.get(path).status_code == 403
    st = gv.get("/admin/stats").json()
    assert st["n_attempts"] >= 1 and len(st["attempts_by_day"]) == 14 and "error_type_names" in st
    rows = {r["email"]: r for r in gv.get("/admin/users").json()}
    assert rows[f"a{P}@ictu.edu.vn"]["n_attempts"] >= 1
    with SessionLocal() as db:
        db.add(Question(document_id=i["shared"], stem=f"{P} câu bị loại?", options={"A": "1", "B": "2", "C": "3", "D": "4"},
                        answer="A", rationales={}, source_chunk_ids=[i["shared_chunk"]], status="rejected",
                        validation={"source_ids": {"passed": True}, "form": {"passed": False, "reason": "form",
                                    "details": {"rule": "double_negation"}}}))
        failed = Document(filename=f"{P}failed.pdf", file_path="x", status="failed", error="lỗi thử", is_shared=True)
        db.add(failed)
        db.commit()
        failed_id = failed.id
    bank = gv.get(f"/admin/documents/{i['shared']}/questions?status=rejected").json()
    assert bank and bank[0]["reject_reason"] == "Sai hình thức: Phủ định kép"
    assert gv.post(f"/admin/documents/{i['shared']}/reprocess").status_code == 409     # bài không lỗi
    assert gv.post(f"/admin/documents/{failed_id}/reprocess").status_code == 202
    assert gv.get(f"/documents/{failed_id}").json()["status"] == "uploaded"
    assert gv.get(f"/admin/users/{i['a']}/attempts").status_code == 200
    docs = {d["id"]: d for d in gv.get("/documents").json()}
    assert docs[i["a_priv"]]["owner_email"] == f"a{P}@ictu.edu.vn"
    assert all(d["owner_email"] is None for d in a.get("/documents").json())      # sinh viên không thấy email
