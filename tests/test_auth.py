"""Kiểm thử đăng nhập Google (OIDC + PKCE), phiên, CSRF, phân quyền — qua API thật trên Postgres.

Google được thay bằng bản giả: tự sinh khóa RSA, ký ID token như Google, nên phần xác minh chữ ký, iss, aud,
nonce, email_verified, tên miền chạy thật. Cần TEST_DATABASE_URL đã chạy migrations 001–005.
  TEST_DATABASE_URL=$DATABASE_URL python -m pytest -q tests/test_auth.py
Dữ liệu thử có email đuôi "__t@ictu.edu.vn", được xóa khi xong.
"""
import os
import time
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="cần TEST_DATABASE_URL")

CLIENT_ID = "test-client.apps.googleusercontent.com"
BASE = "http://testserver"
TAG = "__t@ictu.edu.vn"


class FakeGoogle:
    def __init__(self):
        from joserfc.jwk import RSAKey
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        self.next_claims: dict = {}
        self.codes: dict[str, dict] = {}

    def jwks(self):
        return {"keys": [self.key.as_dict(private=False)]}

    def sign(self, claims, key=None):
        from joserfc import jwt
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key or self.key)

    def claims(self, email, nonce, **over):
        now = int(time.time())
        c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "sub-" + email, "email": email,
             "email_verified": True, "hd": email.split("@")[1], "name": "SV " + email.split("@")[0],
             "picture": "https://x/a.png", "nonce": nonce, "iat": now, "exp": now + 3600}
        c.update(over)
        return {k: v for k, v in c.items() if v is not None}


@pytest.fixture(scope="module")
def env():
    os.environ.update({
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"], "GOOGLE_CLIENT_ID": CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": "secret", "GOOGLE_ALLOWED_DOMAIN": "ictu.edu.vn",
        "ADMIN_EMAILS": f"gv{TAG}", "PUBLIC_BASE_URL": BASE, "SESSION_SECRET": "x" * 40,
        "COOKIE_SECURE": "false", "AUTH_REQUIRED": "true",
    })
    from app.auth import get_oidc
    from app.auth.ratelimit import auth_limiter
    from app.config import get_settings
    get_settings.cache_clear()
    get_oidc.cache_clear()
    fake = FakeGoogle()
    oidc = get_oidc()
    oidc.fetch_jwks = fake.jwks
    state = {"override": None}

    def exchange(code, redirect_uri, verifier):
        assert redirect_uri == BASE + "/api/auth/callback"
        info = fake.codes.pop(code)
        import base64, hashlib
        ch = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert ch == info["challenge"], "PKCE sai"
        over = dict(info["over"])
        nonce = over.pop("nonce", info["nonce"])
        claims = fake.claims(info["email"], nonce, **over)
        return {"id_token": state["override"] or fake.sign(claims)}

    oidc.exchange_code = exchange
    yield fake, state, auth_limiter
    from sqlalchemy import delete
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email.like(f"%{TAG}")))
        db.execute(delete(User).where(User.code.like(f"%{TAG}")))
        db.commit()
    for k in ("AUTH_REQUIRED", "GOOGLE_CLIENT_ID", "ADMIN_EMAILS", "SESSION_SECRET", "PUBLIC_BASE_URL"):
        os.environ.pop(k, None)
    get_settings.cache_clear()
    get_oidc.cache_clear()


def new_client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, base_url=BASE, follow_redirects=False)


def login(env, email, next_="/", tamper_state=False, **over):
    """Chạy trọn luồng: /auth/login → (Google giả) → /auth/callback. Trả (client, response callback)."""
    fake, _, limiter = env
    limiter.reset()
    c = new_client()
    r = c.get("/auth/login", params={"next": next_})
    assert r.status_code == 303
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["hd"] == ["ictu.edu.vn"]
    assert q["redirect_uri"] == [BASE + "/api/auth/callback"]
    code = "code-" + email
    fake.codes[code] = {"email": email, "nonce": q["nonce"][0], "challenge": q["code_challenge"][0], "over": over}
    state = "sai" if tamper_state else q["state"][0]
    return c, c.get("/auth/callback", params={"code": code, "state": state})


def err(r):
    return parse_qs(urlsplit(r.headers["location"]).query).get("error", [None])[0]


def test_login_success_and_me(env):
    c, r = login(env, f"sv1{TAG}", next_="/quiz/5")
    assert r.status_code == 303 and r.headers["location"] == BASE + "/quiz/5"
    cookie = r.headers["set-cookie"]
    assert "rq_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    me = c.get("/auth/me").json()
    assert me["email"] == f"sv1{TAG}" and me["is_admin"] is False and len(me["csrf_token"]) > 20
    # đăng nhập lần 2 cùng tài khoản: cùng user, phiên mới khác mã
    c2, _ = login(env, f"sv1{TAG}")
    me2 = c2.get("/auth/me").json()
    assert me2["user_id"] == me["user_id"] and me2["csrf_token"] != me["csrf_token"]


def test_token_stored_hashed(env):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import AuthSession
    c, r = login(env, f"sv2{TAG}")
    raw = c.cookies.get("rq_session")
    with SessionLocal() as db:
        hashes = set(db.scalars(select(AuthSession.token_hash)))
    assert raw not in hashes


def test_wrong_domain_rejected(env):
    _, r = login(env, "sv@gmail.com", hd=None)
    assert err(r) == "domain"
    _, r = login(env, "sv@ictu.edu.vn.evil.com", hd="ictu.edu.vn")     # hd giả nhưng email khác miền
    assert err(r) == "domain"


def test_unverified_email_rejected(env):
    _, r = login(env, f"sv3{TAG}", email_verified=False)
    assert err(r) == "unverified"


def test_bad_tokens_rejected(env):
    _, r = login(env, f"sv4{TAG}", tamper_state=True)
    assert err(r) == "state"
    _, r = login(env, f"sv4{TAG}", aud="other-app")
    assert err(r) == "token"
    _, r = login(env, f"sv4{TAG}", nonce="replayed")
    assert err(r) == "token"
    _, r = login(env, f"sv4{TAG}", exp=int(time.time()) - 600)
    assert err(r) == "token"
    _, r = login(env, f"sv4{TAG}", iss="https://evil.com")
    assert err(r) == "token"
    # chữ ký bằng khóa khác (giả mạo Google)
    from joserfc.jwk import RSAKey
    fake, state, _ = env
    other = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    state["override"] = fake.sign(fake.claims(f"sv4{TAG}", "x"), other)
    try:
        _, r = login(env, f"sv4{TAG}")
        assert err(r) == "token"
    finally:
        state["override"] = None


def test_callback_without_tx_cookie(env):
    c = new_client()
    r = c.get("/auth/callback", params={"code": "x", "state": "y"})
    assert err(r) == "expired"
    r = c.get("/auth/callback", params={"error": "access_denied"})
    assert err(r) == "cancelled"


def test_open_redirect_blocked(env):
    for bad in ("//evil.com", "https://evil.com", "/\\evil.com"):
        _, r = login(env, f"sv5{TAG}", next_=bad)
        assert r.headers["location"] == BASE + "/"


def test_requires_login_when_enabled(env):
    c = new_client()
    assert c.get("/documents").status_code == 401
    assert c.get("/auth/me").status_code == 401
    assert c.post("/users/login", json={"code": "abc"}).status_code == 410
    c, _ = login(env, f"sv6{TAG}")
    assert c.get("/documents").status_code == 200


def test_csrf_and_origin(env):
    c, _ = login(env, f"sv7{TAG}")
    csrf = c.get("/auth/me").json()["csrf_token"]
    body = {"scope": {}, "n": 5}
    assert c.post("/quizzes", json=body).status_code == 403                        # thiếu token
    assert c.post("/quizzes", json=body, headers={"X-CSRF-Token": "sai"}).status_code == 403
    r = c.post("/quizzes", json=body, headers={"X-CSRF-Token": csrf, "Origin": "https://evil.com"})
    assert r.status_code == 403
    r = c.post("/quizzes", json=body, headers={"X-CSRF-Token": csrf, "Origin": BASE})
    assert r.status_code not in (401, 403)                                          # qua được lớp bảo vệ


def test_admin_only_endpoints(env):
    c, _ = login(env, f"sv8{TAG}")
    csrf = c.get("/auth/me").json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    # Từ Đợt 0 sinh viên được tải / xóa slide riêng của mình; quyền với bài chung kiểm tra ở test_access.py.
    # Bài không tồn tại (hoặc không được xem) → 404, không để lộ là có tồn tại hay không.
    assert c.delete("/documents/999999", headers=h).status_code == 404
    assert c.post("/documents/999999/questions/generate", json={}, headers=h).status_code == 404
    a, _ = login(env, f"gv{TAG}")
    me = a.get("/auth/me").json()
    assert me["is_admin"] is True
    assert a.delete("/documents/999999", headers={"X-CSRF-Token": me["csrf_token"]}).status_code == 404


def test_cannot_view_others(env):
    c1, _ = login(env, f"sv9{TAG}")
    c2, _ = login(env, f"sv10{TAG}")
    uid1 = c1.get("/auth/me").json()["user_id"]
    assert c2.get(f"/users/{uid1}/profile").status_code == 403
    assert c1.get(f"/users/{uid1}/profile").status_code == 200


def test_user_id_spoof_ignored(env):
    """Gửi user_id của người khác khi nộp bài/tạo đề: hệ thống vẫn dùng người dùng của phiên."""
    from app.auth.deps import effective_user_id
    from app.models import User
    assert effective_user_id(User(id=7), 99) == 7
    assert effective_user_id(None, 99) == 99


def test_logout_and_logout_all(env):
    c, _ = login(env, f"sv11{TAG}")
    c2, _ = login(env, f"sv11{TAG}")
    csrf = c.get("/auth/me").json()["csrf_token"]
    assert c.post("/auth/logout", headers={"X-CSRF-Token": "sai"}).status_code == 403
    assert c.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    c.cookies.clear()
    assert c.get("/auth/me").status_code == 401
    assert c2.get("/auth/me").status_code == 200
    c3, _ = login(env, f"sv11{TAG}")
    csrf3 = c3.get("/auth/me").json()["csrf_token"]
    assert c3.post("/auth/logout-all", headers={"X-CSRF-Token": csrf3}).status_code == 204
    assert c2.get("/auth/me").status_code == 401


def test_session_expiry(env):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.db import SessionLocal
    from app.models import AuthSession
    c, _ = login(env, f"sv12{TAG}")
    uid = c.get("/auth/me").json()["user_id"]
    with SessionLocal() as db:
        db.execute(update(AuthSession).where(AuthSession.user_id == uid).values(
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=8)))
        db.commit()
    assert c.get("/auth/me").status_code == 401


def test_rate_limit(env):
    _, _, limiter = env
    limiter.reset()
    c = new_client()
    codes = [c.get("/auth/login").status_code for _ in range(22)]
    assert codes[:20] == [303] * 20 and codes[-1] == 429
    limiter.reset()


def test_link_legacy_user_by_email(env):
    """Sinh viên đã từng dùng mã = email ở giao diện cũ: đăng nhập Google nối vào đúng tài khoản đó."""
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = User(code=f"old{TAG}")
        db.add(u)
        db.commit()
        old_id = u.id
    c, _ = login(env, f"old{TAG}")
    assert c.get("/auth/me").json()["user_id"] == old_id
