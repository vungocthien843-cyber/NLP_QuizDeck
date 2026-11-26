-- Đăng nhập bằng tài khoản Google của trường (OpenID Connect) và phiên đăng nhập phía server.
-- Chạy lại an toàn (IF NOT EXISTS). Chạy SAU 001–004.

ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub    TEXT UNIQUE;     -- mã định danh cố định của tài khoản Google
ALTER TABLE users ADD COLUMN IF NOT EXISTS email         TEXT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url    TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin      BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sessions (
  id            BIGSERIAL PRIMARY KEY,
  user_id       INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    TEXT NOT NULL UNIQUE,          -- SHA-256 của mã phiên; mã gốc chỉ nằm trong cookie của trình duyệt
  csrf_token    TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL,          -- hạn tuyệt đối
  user_agent    TEXT,
  ip            TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
