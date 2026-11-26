-- Phiên bản 3: đáp án nhiễu chẩn đoán và dữ liệu người học (docs/ke-hoach-v3.md, mục 5;
-- docs/ke-hoach-v3-chi-tiet.md, nhóm B–E).
--
-- Volume mới: chạy tự động sau 001_init.sql và 002_v2.sql.
-- DB đang có dữ liệu: SAO LƯU trước, rồi chạy tay một lần:
--   docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/truoc_003.dump'
--   docker compose cp db:/tmp/truoc_003.dump ./truoc_003.dump
--   docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/003_v3.sql'
-- Viết dạng IF NOT EXISTS và chạy trong một transaction: chạy lại nhiều lần không sao, lỗi giữa chừng thì không
-- thay đổi gì. Chỉ THÊM cột và bảng, không sửa hay xoá dữ liệu cũ; code hiện tại vẫn chạy bình thường sau khi chạy.

BEGIN;

-- ---------- Câu hỏi ----------
-- option_meta: chữ cái → vai trò của phương án sau khi xáo (B5). Ví dụ:
--   {"A": {"role": "key"},
--    "B": {"role": "distractor", "candidate_id": 123, "source": "llm", "error_type": "dao_nhan_qua"}, ...}
ALTER TABLE questions ADD COLUMN IF NOT EXISTS option_meta    JSONB;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS concept        TEXT;              -- ý kiến thức (key_point), dùng cho hồ sơ người học
ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty_est TEXT;              -- easy | medium | hard (D4)
ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty_elo REAL NOT NULL DEFAULT 1200;   -- D7
ALTER TABLE questions ADD COLUMN IF NOT EXISTS history        JSONB NOT NULL DEFAULT '[]'::jsonb;  -- các lần thay đáp án nhiễu (E3)

DO $$ BEGIN
  ALTER TABLE questions ADD CONSTRAINT questions_difficulty_est_check
    CHECK (difficulty_est IS NULL OR difficulty_est IN ('easy', 'medium', 'hard'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- concept cho câu đã có: lấy từ validation.key_point (bank_builder đã lưu sẵn)
UPDATE questions SET concept = validation->>'key_point'
WHERE concept IS NULL AND validation ? 'key_point';

CREATE INDEX IF NOT EXISTS questions_difficulty_idx ON questions (document_id, status, difficulty_est);

-- Nhãn hiểu nhầm do chính LLM tự khai lúc sinh, giữ lại khi bước gắn nhãn (B2) chọn nhãn khác
ALTER TABLE distractor_candidates ADD COLUMN IF NOT EXISTS error_type_self TEXT;

-- ---------- Người học ----------
CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  code          TEXT NOT NULL UNIQUE,            -- mã người học tự nhập (ví dụ mã sinh viên)
  display_name  TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE attempts ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id);
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS mode    TEXT NOT NULL DEFAULT 'normal';
DO $$ BEGIN
  ALTER TABLE attempts ADD CONSTRAINT attempts_mode_check
    CHECK (mode IN ('normal', 'difficulty', 'weakness', 'auto'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE INDEX IF NOT EXISTS attempts_user_idx ON attempts (user_id, submitted_at);

ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS user_id    INT REFERENCES users(id);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS mode       TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS difficulty TEXT;

-- Vì sao câu được chọn vào đề (D6), ví dụ {"weak_concept": "...", "error_type": "...", "score": 2.5}
ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS reason JSONB;

-- Một dòng cho mỗi câu trả lời (C2). attempts.answers vẫn giữ để tương thích ngược.
CREATE TABLE IF NOT EXISTS responses (
  id            BIGSERIAL PRIMARY KEY,
  attempt_id    INT    NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  user_id       INT    REFERENCES users(id),
  question_id   BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  chosen        TEXT,                              -- chữ cái (mcq); NULL nếu bỏ trống
  answer_payload JSONB,                            -- đáp án của các dạng câu khác (nhóm F)
  is_correct    BOOLEAN NOT NULL,
  score         REAL,                              -- điểm từng phần 0–1 (nhóm F); mcq = 0 hoặc 1
  candidate_id  BIGINT REFERENCES distractor_candidates(id) ON DELETE SET NULL,
  error_type    TEXT,                              -- loại hiểu nhầm của phương án sai đã chọn
  concept       TEXT,
  time_ms       INT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS responses_user_idx     ON responses (user_id, created_at);
CREATE INDEX IF NOT EXISTS responses_question_idx ON responses (question_id);
CREATE INDEX IF NOT EXISTS responses_attempt_idx  ON responses (attempt_id);

-- Hồ sơ hiểu nhầm (D3): điểm có suy giảm theo thời gian, cập nhật sau mỗi lần nộp bài
CREATE TABLE IF NOT EXISTS misconception_stats (
  user_id     INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  concept     TEXT NOT NULL,
  error_type  TEXT NOT NULL,
  score       REAL NOT NULL DEFAULT 0,
  n_seen      INT  NOT NULL DEFAULT 0,
  last_seen   TIMESTAMPTZ,
  PRIMARY KEY (user_id, concept, error_type)
);

-- Mức thành thạo theo khái niệm (D7, D8)
CREATE TABLE IF NOT EXISTS user_skill (
  user_id     INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  concept     TEXT NOT NULL,
  elo         REAL NOT NULL DEFAULT 1200,
  n_answered  INT  NOT NULL DEFAULT 0,
  n_correct   INT  NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, concept)
);

-- ---------- Phân tích câu hỏi (nhóm E) ----------
CREATE TABLE IF NOT EXISTS item_flags (
  id           BIGSERIAL PRIMARY KEY,
  question_id  BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  letter       TEXT,                              -- NULL = cờ cho cả câu
  flag         TEXT NOT NULL CHECK (flag IN ('unused_distractor', 'upper_group_attracted',
                                             'beats_key', 'low_discrimination')),
  stats        JSONB,
  resolved     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS item_flags_open_idx ON item_flags (question_id) WHERE NOT resolved;

COMMIT;
