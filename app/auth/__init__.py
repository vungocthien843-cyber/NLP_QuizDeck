"""Đăng nhập bằng tài khoản Google của trường (xem google.py, sessions.py, deps.py)."""
from functools import lru_cache

from app.auth.google import GoogleOIDC
from app.config import get_settings


@lru_cache
def get_oidc() -> GoogleOIDC:
    s = get_settings()
    return GoogleOIDC(s.google_client_id, s.google_client_secret, s.google_allowed_domain)
