"""Kiểm thử giao diện từ đầu đến cuối (Playwright) trên hệ thống đang chạy bằng Docker.

Chạy bằng scripts\\10_kiem_thu_giao_dien.bat (docker compose --profile e2e run --rm e2e).
- Trình duyệt mở http://localhost:8080 (container e2e dùng chung mạng với container web).
- Không đăng nhập Google thật: tạo sẵn 2 tài khoản thử (sinh viên, quản trị) và phiên đăng nhập ngay trong database.
- Không gọi LLM (không tốn phí): không tải slide, không hỏi trợ lý.
- Dữ liệu thử có email đuôi "__e2e@ictu.edu.vn"; dọn sạch khi xong, kể cả số lần dùng (times_used) của câu hỏi.
"""
import os
import sys

import pytest

sys.path.insert(0, os.environ.get("REPO_DIR", "/repo"))

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8080")
TAG = "__e2e@ictu.edu.vn"


def _cleanup(db):
    from sqlalchemy import delete, select, update

    from app.models import (Attempt, AuthSession, ChatMessage, Conversation, Feedback, MisconceptionStat, Question,
                            Quiz, QuizQuestion, Response, User)
    uids = list(db.scalars(select(User.id).where(User.email.like(f"%{TAG}"))))
    if not uids:
        return
    quiz_ids = list(db.scalars(select(Quiz.id).where(Quiz.user_id.in_(uids))))
    for qid in db.scalars(select(QuizQuestion.question_id).where(QuizQuestion.quiz_id.in_(quiz_ids))):
        db.execute(update(Question).where(Question.id == qid, Question.times_used > 0)
                   .values(times_used=Question.times_used - 1))
    conv_ids = list(db.scalars(select(Conversation.id).where(Conversation.user_id.in_(uids))))
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
    db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
    att_ids = list(db.scalars(select(Attempt.id).where(Attempt.user_id.in_(uids))))
    db.execute(delete(Feedback).where(Feedback.attempt_id.in_(att_ids)))
    db.execute(delete(Response).where(Response.attempt_id.in_(att_ids)))
    db.execute(delete(Attempt).where(Attempt.id.in_(att_ids)))
    db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids)))
    db.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
    db.execute(delete(MisconceptionStat).where(MisconceptionStat.user_id.in_(uids)))
    db.execute(delete(AuthSession).where(AuthSession.user_id.in_(uids)))
    db.execute(delete(User).where(User.id.in_(uids)))
    db.commit()


@pytest.fixture(scope="session")
def accounts():
    from app.auth.sessions import create_session
    from app.db import SessionLocal
    from app.models import User
    out = {}
    with SessionLocal() as db:
        _cleanup(db)                       # lần chạy trước dừng giữa chừng
        for key, name, admin in (("sv", "Sinh viên Thử", False), ("gv", "Quản trị Thử", True)):
            u = User(code=f"{key}{TAG}", email=f"{key}{TAG}", display_name=name, is_admin=admin)
            db.add(u)
            db.commit()
            out[key] = create_session(db, u, "e2e", "127.0.0.1")[0]
    yield out
    with SessionLocal() as db:
        _cleanup(db)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page_as(browser, accounts):
    """page_as("sv" | "gv" | None) → trang đã đăng nhập (None = chưa đăng nhập). Ghi lỗi JavaScript vào page.js_errors."""
    contexts = []

    def make(who):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="vi-VN")
        if who:
            ctx.add_cookies([{"name": os.environ.get("SESSION_COOKIE", "rq_session"), "value": accounts[who], "url": BASE}])
        contexts.append(ctx)
        page = ctx.new_page()
        page.js_errors = []
        page.on("pageerror", lambda e: page.js_errors.append(str(e)))
        page.set_default_timeout(15000)
        return page

    yield make
    for c in contexts:
        c.close()


@pytest.fixture(scope="session")
def quiz_doc():
    """Bài trong thư viện chung đã sẵn sàng và có đủ 10 câu hỏi đạt (để tạo đề)."""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Document, Question
    with SessionLocal() as db:
        row = db.execute(select(Document.id, Document.filename, func.count(Question.id))
                         .join(Question, Question.document_id == Document.id)
                         .where(Document.is_active, Document.is_shared, Document.status == "ready",
                                Question.status == "accepted")
                         .group_by(Document.id).having(func.count(Question.id) >= 10)
                         .order_by(Document.session_no.nulls_last(), Document.id)).first()
    if row is None:
        pytest.skip("Chưa có bài nào trong thư viện chung có từ 10 câu hỏi trở lên")
    return {"id": row[0], "filename": row[1]}
