"""Phân quyền tài liệu.

- Thư viện chung (is_shared = true): mọi người đã đăng nhập đều xem, tạo đề, hỏi trợ lý được.
- Slide riêng (is_shared = false): chỉ chủ sở hữu (owner_user_id) và quản trị viên.
- Không có người dùng (AUTH_REQUIRED = false, giao diện Streamlit cũ): không giới hạn, giữ hành vi cũ.

Mọi chỗ đọc nội dung tài liệu (danh sách, ảnh slide, chunk, tìm kiếm, tạo đề, trợ lý) phải đi qua các hàm ở
đây, để slide riêng của sinh viên này không lọt sang sinh viên khác, kể cả gián tiếp qua câu trả lời của trợ lý.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.models import Document, Quiz, User
from app.schemas import Scope

NO_DOC = -1          # id không tồn tại: Scope(document_ids=[]) bị hiểu là "không lọc", nên dùng [-1] cho "không có gì"


def unrestricted(user: User | None) -> bool:
    return user is None or user.is_admin


def visible_clause(user: User | None) -> ColumnElement[bool]:
    """Điều kiện SQL: tài liệu đang hoạt động mà người dùng được xem."""
    if unrestricted(user):
        return Document.is_active.is_(True)
    return Document.is_active.is_(True) & or_(Document.is_shared.is_(True), Document.owner_user_id == user.id)


def can_view(user: User | None, doc: Document | None) -> bool:
    if doc is None or not doc.is_active:
        return False
    return unrestricted(user) or doc.is_shared or doc.owner_user_id == user.id


def can_edit(user: User | None, doc: Document) -> bool:
    """Xóa, sinh thêm câu hỏi, đổi số buổi: quản trị viên, hoặc chủ của slide riêng."""
    return unrestricted(user) or (not doc.is_shared and doc.owner_user_id == user.id)


def get_visible(db: Session, user: User | None, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if not can_view(user, doc):
        raise HTTPException(404, "Không tìm thấy tài liệu")     # 404 thay vì 403: không để lộ là tài liệu có tồn tại
    return doc


def get_editable(db: Session, user: User | None, document_id: int) -> Document:
    doc = get_visible(db, user, document_id)
    if not can_edit(user, doc):
        raise HTTPException(403, "Chỉ quản trị viên hoặc người tải slide lên được thực hiện thao tác này")
    return doc


def visible_ids(db: Session, user: User | None) -> list[int] | None:
    """None = không giới hạn; ngược lại là danh sách id tài liệu được xem."""
    if unrestricted(user):
        return None
    return list(db.scalars(select(Document.id).where(visible_clause(user))))


def restrict_scope(db: Session, user: User | None, scope: Scope | None) -> Scope:
    """Phạm vi tạo đề / tìm kiếm / trợ lý giới hạn trong tài liệu người dùng được xem.
    Xin tài liệu không được xem thì báo 404 (không âm thầm bỏ qua để người dùng biết phạm vi sai)."""
    scope = scope.model_copy() if scope else Scope()
    allowed = visible_ids(db, user)
    if allowed is None:
        return scope
    if scope.document_ids:
        bad = set(scope.document_ids) - set(allowed)
        if bad:
            raise HTTPException(404, "Không tìm thấy tài liệu")
        return scope
    scope.document_ids = allowed or [NO_DOC]
    return scope


def can_view_quiz(user: User | None, quiz: Quiz | None) -> bool:
    """Đề do người khác tạo (có user_id) thì không xem được; đề chung (user_id rỗng, ví dụ đề thử nghiệm) ai cũng xem."""
    if quiz is None:
        return False
    return unrestricted(user) or quiz.user_id is None or quiz.user_id == user.id

