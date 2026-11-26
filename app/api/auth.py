"""API đăng nhập: /auth/login → Google → /auth/callback → cookie phiên; /auth/me, /auth/logout, /auth/logout-all.

Trình duyệt truy cập qua nginx: /api/auth/... được chuyển tới /auth/... của FastAPI, nên redirect URI khai báo với
Google là <public_base_url>/api/auth/callback.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_oidc
from app.auth.deps import current_session, require_login
from app.auth.google import GoogleIdentity, LoginError, new_pkce
from app.auth.ratelimit import auth_limiter
from app.auth.sessions import create_session, revoke, revoke_all
from app.config import get_settings
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

TX_COOKIE = "rq_oidc_tx"
TX_MAX_AGE = 600


class MeOut(BaseModel):
    user_id: int
    email: str | None
    name: str | None
    avatar_url: str | None
    is_admin: bool
    csrf_token: str


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if len(secret) < 32:
        raise HTTPException(500, "Chưa cấu hình SESSION_SECRET (ít nhất 32 ký tự)")
    return URLSafeTimedSerializer(secret, salt="oidc-tx")


def _redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + "/api/auth/callback"


def _safe_next(path: str | None) -> str:
    """Chỉ cho chuyển về đường dẫn nội bộ, chặn open redirect (//evil.com, \\evil.com, http://...)."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or "\n" in path:
        return "/"
    return path


def _fail(code: str) -> RedirectResponse:
    res = RedirectResponse(get_settings().public_base_url.rstrip("/") + f"/login?error={code}", status_code=303)
    res.delete_cookie(TX_COOKIE, path="/")
    return res


def _set_cookie(res: Response, name: str, value: str, max_age: int) -> None:
    res.set_cookie(name, value, max_age=max_age, path="/", httponly=True,
                   secure=get_settings().cookie_secure, samesite="lax")


def upsert_user(db: Session, ident: GoogleIdentity) -> User:
    """Tìm theo google_sub (cố định); chưa có thì nối với người dùng cũ cùng email/mã, nếu không thì tạo mới."""
    user = db.scalar(select(User).where(User.google_sub == ident.sub))
    if user is None:
        user = db.scalar(select(User).where((User.email == ident.email) | (User.code == ident.email)))
        if user is not None and user.google_sub and user.google_sub != ident.sub:
            raise LoginError("conflict", "Email đã gắn với tài khoản Google khác")
        if user is None:
            user = User(code=ident.email)
            db.add(user)
        user.google_sub = ident.sub
    user.email = ident.email
    user.display_name = ident.name or user.display_name
    user.avatar_url = ident.picture
    user.is_admin = ident.email in get_settings().admin_email_set
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


@router.get("/login", dependencies=[Depends(auth_limiter)])
def login(next: str = "/") -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise HTTPException(500, "Chưa cấu hình GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = new_pkce()
    tx = _serializer().dumps({"state": state, "nonce": nonce, "verifier": verifier, "next": _safe_next(next)})
    res = RedirectResponse(get_oidc().authorization_url(_redirect_uri(), state, nonce, challenge), status_code=303)
    _set_cookie(res, TX_COOKIE, tx, TX_MAX_AGE)
    return res


@router.get("/callback", dependencies=[Depends(auth_limiter)])
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)) -> RedirectResponse:
    if error:                                     # người dùng bấm Hủy ở trang Google
        return _fail("cancelled")
    raw = request.cookies.get(TX_COOKIE)
    try:
        tx = _serializer().loads(raw or "", max_age=TX_MAX_AGE)
    except BadSignature:
        return _fail("expired")
    if not code or not state or not secrets.compare_digest(state, tx["state"]):
        return _fail("state")
    try:
        tokens = get_oidc().exchange_code(code, _redirect_uri(), tx["verifier"])
        ident = get_oidc().verify_id_token(tokens.get("id_token", ""), tx["nonce"])
        user = upsert_user(db, ident)
    except LoginError as exc:
        log.warning("Đăng nhập thất bại (%s): %s", exc.code, exc)
        return _fail(exc.code)
    token, _ = create_session(db, user, request.headers.get("user-agent"),
                              request.client.host if request.client else None)
    res = RedirectResponse(get_settings().public_base_url.rstrip("/") + tx["next"], status_code=303)
    res.delete_cookie(TX_COOKIE, path="/")
    _set_cookie(res, get_settings().session_cookie, token, get_settings().session_max_days * 86400)
    log.info("Đăng nhập: user %s", user.id)
    return res


@router.get("/me", response_model=MeOut)
def me(found=Depends(current_session), _: User = Depends(require_login)) -> MeOut:
    session, user = found
    return MeOut(user_id=user.id, email=user.email, name=user.display_name, avatar_url=user.avatar_url,
                 is_admin=user.is_admin, csrf_token=session.csrf_token)


@router.post("/logout", status_code=204)
def logout(found=Depends(current_session), db: Session = Depends(get_db)) -> Response:
    res = Response(status_code=204)
    if found:
        revoke(db, found[0])
    res.delete_cookie(get_settings().session_cookie, path="/")
    return res


@router.post("/logout-all", status_code=204)
def logout_all(user: User = Depends(require_login), db: Session = Depends(get_db)) -> Response:
    revoke_all(db, user.id)
    res = Response(status_code=204)
    res.delete_cookie(get_settings().session_cookie, path="/")
    return res
