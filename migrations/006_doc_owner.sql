-- Đợt 0: phân quyền tài liệu. Chạy lại an toàn.
-- is_shared = true: thư viện chung (mọi sinh viên thấy); false: slide riêng của owner_user_id.
-- Tài liệu có sẵn trước migration này được giữ là thư viện chung.
BEGIN;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_user_id INT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS documents_owner_idx ON documents (owner_user_id);
-- Hội thoại với trợ lý thuộc về người dùng (để mở lại lịch sử và không cho người khác đọc)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS conversations_user_idx ON conversations (user_id);
COMMIT;
