-- Mốc 3, G4/G5: thử nghiệm với sinh viên (docs/ke-hoach-v3-chi-tiet.md).
-- Chạy một lần trên DB đang có (chuan_bi_thu_nghiem.bat); an toàn khi chạy lại.
BEGIN;

-- Câu hỏi dùng riêng cho đề thử nghiệm: không lọt vào đề tạo ngẫu nhiên / luyện tập (chỉ lấy status = 'accepted')
ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_status_check;
ALTER TABLE questions ADD CONSTRAINT questions_status_check
  CHECK (status IN ('accepted', 'rejected', 'experiment'));

-- Phản hồi của người học: chẩn đoán từng câu có đúng ý không, khảo sát chung sau đề
CREATE TABLE IF NOT EXISTS feedback (
  id           BIGSERIAL PRIMARY KEY,
  user_id      INT    REFERENCES users(id) ON DELETE CASCADE,
  attempt_id   INT    REFERENCES attempts(id) ON DELETE CASCADE,
  question_id  BIGINT REFERENCES questions(id) ON DELETE CASCADE,   -- NULL = câu hỏi khảo sát chung
  kind         TEXT   NOT NULL,      -- diag_item (0 không đúng / 1 một phần / 2 đúng) | diag_overall | explain_overall
                                     -- | practice_useful (1–5) | comment
  value        INT,
  comment      TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_user_idx ON feedback (user_id, attempt_id);
-- Gửi lại thì ghi đè (mỗi người, mỗi bài làm, mỗi câu, mỗi loại câu hỏi một dòng)
CREATE UNIQUE INDEX IF NOT EXISTS feedback_once_idx
  ON feedback (user_id, attempt_id, COALESCE(question_id, 0), kind);

COMMIT;
