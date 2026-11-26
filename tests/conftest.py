"""Đặt DATABASE_URL trước khi bất kỳ test nào import app.db (engine được tạo lúc import).
Container api chạy với AUTH_REQUIRED=true; test backend mặc định tắt đăng nhập, test nào cần (test_auth, test_access)
tự bật trong fixture của mình."""
import os

os.environ["AUTH_REQUIRED"] = "false"

if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
