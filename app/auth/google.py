"""Đăng nhập Google theo OpenID Connect, luồng Authorization Code + PKCE, xử lý hoàn toàn ở backend.

Trình duyệt không bao giờ cầm token của Google: backend đổi mã lấy ID token, tự xác minh ID token
(chữ ký theo JWKS của Google, iss, aud, exp, nonce, email_verified, tên miền hd) rồi mới tạo phiên.
Hai lần gọi mạng (JWKS, đổi mã) nằm trong lớp GoogleOIDC để test thay bằng bản giả.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
JWKS_TTL = 3600


class LoginError(Exception):
    """Lỗi đăng nhập; code là mã ngắn đưa về trang /login?error=<code> để giao diện hiện thông báo."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None
    hd: str | None


def new_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) theo RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class GoogleOIDC:
    def __init__(self, client_id: str, client_secret: str, allowed_domain: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.allowed_domain = allowed_domain.lower().strip()
        self._jwks: dict | None = None
        self._jwks_at = 0.0

    # ---------- bước 1: chuyển sang Google ----------
    def authorization_url(self, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        if self.allowed_domain:
            params["hd"] = self.allowed_domain       # chỉ là gợi ý cho Google; tên miền vẫn được kiểm tra ở verify
        return f"{AUTH_URL}?{urlencode(params)}"

    # ---------- bước 2: đổi mã lấy ID token ----------
    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> dict:
        try:
            res = httpx.post(TOKEN_URL, timeout=10, data={
                "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": code_verifier,
            })
        except httpx.HTTPError as exc:
            raise LoginError("google", f"Không kết nối được Google: {exc}") from exc
        if res.status_code != 200:
            raise LoginError("google", f"Google từ chối đổi mã: {res.status_code}")
        return res.json()

    def fetch_jwks(self) -> dict:
        res = httpx.get(JWKS_URL, timeout=10)
        res.raise_for_status()
        return res.json()

    def _keys(self, force: bool = False):
        if force or self._jwks is None or time.time() - self._jwks_at > JWKS_TTL:
            self._jwks, self._jwks_at = self.fetch_jwks(), time.time()
        return KeySet.import_key_set(self._jwks)

    # ---------- bước 3: xác minh ID token ----------
    def verify_id_token(self, id_token: str, nonce: str) -> GoogleIdentity:
        try:
            try:
                token = jwt.decode(id_token, self._keys(), algorithms=["RS256"])
            except (JoseError, ValueError):
                token = jwt.decode(id_token, self._keys(force=True), algorithms=["RS256"])  # Google xoay khóa
            claims = token.claims
            jwt.JWTClaimsRegistry(leeway=60, exp={"essential": True}, sub={"essential": True}).validate(claims)
        except (JoseError, ValueError) as exc:
            raise LoginError("token", f"ID token không hợp lệ: {exc}") from exc

        if claims.get("iss") not in ISSUERS:
            raise LoginError("token", "Sai iss")
        aud = claims.get("aud")
        if aud != self.client_id and not (isinstance(aud, list) and self.client_id in aud):
            raise LoginError("token", "Sai aud")
        if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise LoginError("token", "Sai nonce")
        email = str(claims.get("email") or "").lower()
        if not email or claims.get("email_verified") not in (True, "true"):
            raise LoginError("unverified", "Email chưa được Google xác minh")
        if self.allowed_domain:
            hd = str(claims.get("hd") or "").lower()
            if hd != self.allowed_domain or not email.endswith("@" + self.allowed_domain):
                raise LoginError("domain", f"Chỉ nhận tài khoản @{self.allowed_domain}")
        return GoogleIdentity(sub=str(claims["sub"]), email=email, name=claims.get("name"),
                              picture=claims.get("picture"), hd=claims.get("hd"))
