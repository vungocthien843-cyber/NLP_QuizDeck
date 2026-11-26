-- Phiên bản 2: pipeline sinh đáp án nhiễu 8 bước (docs/ke-hoach-v2.md, mục 8).
-- Volume mới: chạy tự động sau 001_init.sql. DB đang có dữ liệu: chạy tay một lần
--   docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -f /docker-entrypoint-initdb.d/002_v2.sql
-- Viết dạng IF NOT EXISTS nên chạy lại nhiều lần không sao.

ALTER TABLE questions ADD COLUMN IF NOT EXISTS pipeline_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answer_type TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS selection JSONB;      -- entropy, δ, scorer, xác suất 4 phương án

CREATE TABLE IF NOT EXISTS distractor_candidates (
  id           BIGSERIAL PRIMARY KEY,
  question_id  BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  text         TEXT NOT NULL,
  source       TEXT NOT NULL CHECK (source IN ('vit5', 'llm')),
  error_type   TEXT,
  copy_score   REAL,
  entail_prob  REAL,
  score        REAL,
  rejected_at  TEXT CHECK (rejected_at IN ('form', 'copy', 'nli')),
  selected     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS distractor_candidates_question_idx ON distractor_candidates (question_id);
