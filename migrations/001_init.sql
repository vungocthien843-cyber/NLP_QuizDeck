-- Schema MVP (mục 4 bản thiết kế). Chạy tự động khi khởi tạo container db lần đầu.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id           SERIAL PRIMARY KEY,
  course_id    INT,
  source_type  TEXT NOT NULL DEFAULT 'slide' CHECK (source_type IN ('slide','textbook')),
  filename     TEXT NOT NULL,
  file_path    TEXT NOT NULL,
  session_no   INT,
  status       TEXT NOT NULL DEFAULT 'uploaded'
               CHECK (status IN ('uploaded','parsing','embedding','generating','ready','failed')),
  error        TEXT,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
  id           BIGSERIAL PRIMARY KEY,
  document_id  INT NOT NULL REFERENCES documents(id),
  source_type  TEXT NOT NULL CHECK (source_type IN ('slide','textbook')),
  session_no   INT,
  slide_no     INT,
  slide_end    INT,
  page_no      INT,
  chapter_no   INT,
  title        TEXT,
  raw_text     TEXT NOT NULL,
  notes        TEXT,
  vlm_caption  TEXT,
  embed_text   TEXT NOT NULL,
  image_path   TEXT,
  lang         TEXT,
  embedding    VECTOR(1024),
  sparse       SPARSEVEC(250002),
  tsv          TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', embed_text)) STORED,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (session_no, slide_no);
CREATE INDEX ON chunks (document_id);
-- Không tạo HNSW ở MVP (quét tuần tự, lọc luôn đủ kết quả).

CREATE TABLE questions (
  id               BIGSERIAL PRIMARY KEY,
  document_id      INT NOT NULL REFERENCES documents(id),
  session_no       INT,
  stem             TEXT NOT NULL,
  options          JSONB NOT NULL,
  answer           CHAR(1) NOT NULL CHECK (answer IN ('A','B','C','D')),
  rationales       JSONB NOT NULL,
  explanation      TEXT,
  bloom_level      TEXT CHECK (bloom_level IN ('remember','understand','apply')),
  source_chunk_ids BIGINT[] NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('accepted','rejected')),
  validation       JSONB,
  stem_embedding   VECTOR(1024),
  times_used       INT NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON questions (document_id, status);

CREATE TABLE quizzes (
  id            SERIAL PRIMARY KEY,
  course_id     INT,
  scope         JSONB NOT NULL,
  num_questions INT NOT NULL,
  bloom_mix     JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE quiz_questions (
  quiz_id     INT NOT NULL REFERENCES quizzes(id),
  question_id BIGINT NOT NULL REFERENCES questions(id),
  position    INT NOT NULL,
  PRIMARY KEY (quiz_id, question_id)
);

CREATE TABLE attempts (
  id           SERIAL PRIMARY KEY,
  quiz_id      INT NOT NULL REFERENCES quizzes(id),
  user_name    TEXT,
  answers      JSONB NOT NULL,
  score        REAL,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
  id          BIGSERIAL PRIMARY KEY,
  attempt_id  INT REFERENCES attempts(id),
  question_id BIGINT REFERENCES questions(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id),
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,
  cited_chunk_ids BIGINT[],
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON chat_messages (conversation_id, created_at);
