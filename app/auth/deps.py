"""Dependency FastAPI cho đăng nhập: current_user, require_user, require_admin.

- Danh tính người dùng luôn lấy từ phiên (cookie), không lấy user_id do giao diện gửi lên.
- Yêu cầu thay đổi dữ liệu (POST/PUT/PATCH/DELETE) có phiên phải kèm header X-CSRF-Token khớp với phiên, và nếu
  trình duyệt gửi Origin thì Origin phải đúng địa chỉ của hệ thống (chống giả mạo yêu cầu, CSRF).
- auth_required = False (giai đoạn chuyển tiếp, giao diện Streamlit cũ vẫn chạy): không có phiên vẫn cho qua.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.sessions import load_session
from app.config import get_settings
from app.db import get_db
from app.models import AuthSession, User

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "X-CSRF-Token"


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


def check_csrf(request: Request, session: AuthSession) -> None:
    if request.method not in UNSAFE:
        return
    origin = request.headers.get("origin")
    if origin and _origin(origin) != _origin(get_settings().public_base_url):
        raise HTTPException(403, "Yêu cầu đến từ nguồn không hợp lệ")
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not secrets.compare_digest(sent, session.csrf_token):
        raise HTTPException(403, "Thiếu hoặc sai CSRF token")


def current_session(request: Request, db: Session = Depends(get_db)) -> tuple[AuthSession, User] | None:
    found = load_session(db, request.cookies.get(get_settings().session_cookie))
    if found:
        check_csrf(request, found[0])
        request.state.user = found[1]
    return found


def current_user(found=Depends(current_session)) -> User | None:
    return found[1] if found else None


def require_user(user: User | None = Depends(current_user)) -> User | None:
    if user is None and get_settings().auth_required:
        raise HTTPException(401, "Cần đăng nhập")
    return user


def require_login(user: User | None = Depends(current_user)) -> User:
    """Luôn bắt đăng nhập, kể cả khi auth_required = False (dùng cho /auth/me, /auth/logout)."""
    if user is None:
        raise HTTPException(401, "Cần đăng nhập")
    return user


def require_admin(user: User | None = Depends(current_user)) -> User | None:
    if not get_settings().auth_required and user is None:
        return None
    if user is None:
        raise HTTPException(401, "Cần đăng nhập")
    if not user.is_admin:
        raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    return user


def effective_user_id(user: User | None, sent: int | None) -> int | None:
    """Có phiên: luôn dùng người dùng của phiên, bỏ qua user_id gửi lên. Không phiên (chế độ cũ): dùng user_id gửi."""
    return user.id if user is not None else sent


def can_view_user(user: User | None, user_id: int | None) -> bool:
    if user is None:
        return not get_settings().auth_required
    return user.is_admin or user_id is None or user.id == user_id
