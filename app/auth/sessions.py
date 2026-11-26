"""Phiên đăng nhập phía server.

Mã phiên 256 bit ngẫu nhiên chỉ nằm trong cookie HttpOnly của trình duyệt; database lưu SHA-256 của nó, nên lộ
database cũng không dùng được để đăng nhập. Mỗi lần đăng nhập tạo mã mới (chống chiếm phiên). Phiên hết hạn khi
không hoạt động quá session_idle_days hoặc quá hạn tuyệt đối session_max_days.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthSession, User

TOUCH_EVERY = timedelta(minutes=5)      # cập nhật last_seen_at tối đa 5 phút một lần, tránh ghi DB mỗi request


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, user_agent: str | None, ip: str | None) -> tuple[str, AuthSession]:
    """Trả (mã phiên gốc để đặt vào cookie, bản ghi phiên)."""
    token = secrets.token_urlsafe(32)
    s = AuthSession(user_id=user.id, token_hash=hash_token(token), csrf_token=secrets.token_urlsafe(32),
                    expires_at=_now() + timedelta(days=get_settings().session_max_days),
                    user_agent=(user_agent or "")[:300] or None, ip=ip)
    db.add(s)
    db.commit()
    return token, s


def load_session(db: Session, token: str | None) -> tuple[AuthSession, User] | None:
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if s is None:
        return None
    now = _now()
    idle = timedelta(days=get_settings().session_idle_days)
    if s.expires_at <= now or s.last_seen_at + idle <= now:
        db.delete(s)
        db.commit()
        return None
    if now - s.last_seen_at > TOUCH_EVERY:
        s.last_seen_at = now
        db.commit()
    user = db.get(User, s.user_id)
    return (s, user) if user else None


def revoke(db: Session, session: AuthSession) -> None:
    db.delete(session)
    db.commit()


def revoke_all(db: Session, user_id: int) -> int:
    n = db.execute(delete(AuthSession).where(AuthSession.user_id == user_id)).rowcount or 0
    db.commit()
    return n


def purge_expired(db: Session) -> int:
    now = _now()
    idle = timedelta(days=get_settings().session_idle_days)
    n = db.execute(delete(AuthSession).where(
        (AuthSession.expires_at <= now) | (AuthSession.last_seen_at <= now - idle))).rowcount or 0
    db.commit()
    return n
