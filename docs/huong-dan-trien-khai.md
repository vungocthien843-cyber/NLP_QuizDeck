# Hướng dẫn triển khai

Tài liệu cho người vận hành hệ thống: cấu hình đăng nhập Google, mở hệ thống cho sinh viên dùng từ máy khác, quản trị và sao lưu.

## 1. Kiến trúc khi chạy

```
Trình duyệt ──► web (nginx, cổng 8080)
                 ├─ /        → giao diện React (thư mục web/)
                 └─ /api/... → api (FastAPI, cổng 8000 trong mạng Docker) ──► db (PostgreSQL + pgvector)
```

- Giao diện và API cùng một địa chỉ nên cookie phiên dùng được `SameSite=Lax`, không cần CORS.
- Cổng 8000 chỉ mở cho chính máy chủ (`127.0.0.1:8000`), dùng để xem `/docs`. Người dùng luôn đi qua nginx.
- `AUTH_REQUIRED` được đặt `true` trong `docker-compose.yml`: mọi API (trừ `/api/auth/*`) cần đăng nhập.

## 2. Đăng nhập Google

### 2.1 Tạo OAuth client (một lần, miễn phí)

1. Vào [Google Cloud Console](https://console.cloud.google.com) (không cần bật thanh toán, bỏ qua lời mời dùng thử 300 USD).
2. Chọn hoặc tạo project → tìm **Google Auth Platform** → **Get started**:
   - App name: tên hiển thị khi sinh viên đăng nhập.
   - Audience: **Internal** nếu tạo bằng tài khoản `@ictu.edu.vn` (chỉ người trong trường đăng nhập được). Nếu tạo bằng Gmail cá nhân thì chọn **External**, để trạng thái **Testing** và thêm email người dùng vào **Test users** (tối đa 100).
3. **Clients** → **Create client** → **Web application**:
   - Authorized JavaScript origins: địa chỉ giao diện, ví dụ `http://localhost:8080`.
   - Authorized redirect URIs: địa chỉ giao diện + `/api/auth/callback`, ví dụ `http://localhost:8080/api/auth/callback`.
4. Chép **Client ID** và **Client secret** vào `.env`.

### 2.2 Biến môi trường (`.env`)

| Biến | Ý nghĩa |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Lấy ở bước 2.1. Không đưa lên git. |
| `GOOGLE_ALLOWED_DOMAIN` | `ictu.edu.vn`. Backend tự kiểm tra tên miền trong ID token (không dựa vào cài đặt của Google). |
| `ADMIN_EMAILS` | Email quản trị viên, cách nhau bởi dấu phẩy. Áp dụng từ lần đăng nhập kế tiếp. |
| `PUBLIC_BASE_URL` | Địa chỉ người dùng mở giao diện, phải khớp redirect URI đã khai với Google. |
| `SESSION_SECRET` | Chuỗi ngẫu nhiên ≥ 32 ký tự: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Đổi chuỗi này làm mọi giao dịch đăng nhập đang dở bị huỷ. |
| `COOKIE_SECURE` | `false` khi chạy `http://localhost`; `true` khi chạy https. |
| `STUDENT_MAX_DOCS`, `STUDENT_MAX_PROCESSING` | Hạn mức slide sinh viên tự tải (mặc định 10 bài, 1 bài xử lý cùng lúc). |

Sau khi sửa `.env`: `docker compose up -d`.

### 2.3 Cơ chế bảo mật (tóm tắt)

- OpenID Connect, luồng Authorization Code + PKCE, xử lý hoàn toàn ở backend; trình duyệt không giữ token của Google.
- Kiểm tra ID token: chữ ký theo JWKS của Google, `iss`, `aud`, `exp`, `nonce`, `email_verified`, tên miền `hd` và đuôi email.
- `state`, `nonce`, `code_verifier` nằm trong cookie có chữ ký, hết hạn sau 10 phút.
- Phiên lưu trong bảng `sessions`, database chỉ giữ SHA-256 của mã phiên. Cookie `HttpOnly`, `SameSite=Lax`. Hết hạn sau 7 ngày không dùng, tối đa 30 ngày.
- Yêu cầu thay đổi dữ liệu phải kèm `X-CSRF-Token` và đúng `Origin`. Giới hạn 20 lần đăng nhập/phút/IP.
- Danh tính luôn lấy từ phiên, không tin `user_id` do trình duyệt gửi.

## 3. Cho sinh viên dùng từ máy khác (https)

Google chỉ cho phép `http` với `localhost`. Máy khác truy cập phải qua **https**. Cách đơn giản nhất là Cloudflare Tunnel (miễn phí, không cần mở cổng router, không cần IP tĩnh).

### 3.1 Cloudflare Tunnel có tên miền riêng (khuyên dùng)

Cần một tên miền đã đưa vào Cloudflare (gói Free).

1. Cloudflare Dashboard → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → loại **Cloudflared** → đặt tên.
2. Chép **token** của tunnel vào `.env`: `CLOUDFLARE_TUNNEL_TOKEN=...`
3. Trong tunnel, thêm **Public hostname**: ví dụ `quiz.<tên-miền>` → Service `HTTP` → `web:8080`.
4. Sửa `.env`:
   ```
   PUBLIC_BASE_URL=https://quiz.<tên-miền>
   COOKIE_SECURE=true
   ```
5. Google Cloud Console → Client → thêm origin `https://quiz.<tên-miền>` và redirect URI `https://quiz.<tên-miền>/api/auth/callback`.
6. Chạy:
   ```
   docker compose --profile tunnel up -d
   ```

Sinh viên mở `https://quiz.<tên-miền>`. Muốn dùng cả `http://localhost:8080` trên máy chủ thì giữ origin/redirect URI localhost trên Google, nhưng `PUBLIC_BASE_URL` chỉ nhận một địa chỉ: đăng nhập sẽ luôn quay về địa chỉ đó.

### 3.2 Chạy thử nhanh không cần tên miền

`docker run --rm --network project_nlp_default cloudflare/cloudflared tunnel --url http://web:8080` in ra một địa chỉ `https://<ngẫu nhiên>.trycloudflare.com`. Địa chỉ đổi sau mỗi lần chạy, nên mỗi lần phải sửa `PUBLIC_BASE_URL` và thêm redirect URI mới trên Google (có thể mất vài phút mới có hiệu lực). Chỉ hợp cho buổi demo ngắn.

## 4. Quản trị

- Trang **Quản trị** (chỉ hiện với email trong `ADMIN_EMAILS`):
  - **Tổng quan**: số sinh viên, lượt làm bài 14 ngày, tỉ lệ đúng theo bài, kiểu hiểu nhầm phổ biến của cả lớp.
  - **Bài giảng**: tải bài vào thư viện môn học, đặt số buổi, sinh thêm câu hỏi, xử lý lại bài lỗi, đưa slide riêng của sinh viên vào thư viện, xoá bài. Bấm tên bài để xem ngân hàng câu hỏi (cả câu bị loại kèm lý do).
  - **Sinh viên**: danh sách tài khoản, điểm, tỉ lệ đúng; bấm vào để xem hồ sơ hiểu nhầm và lịch sử làm bài.
- Thu hồi quyền quản trị: bỏ email khỏi `ADMIN_EMAILS`, `docker compose up -d`; quyền mất từ lần đăng nhập kế tiếp của người đó.

## 5. Sao lưu và khôi phục

```
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups\ragquiz.dump
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean' < backups\ragquiz.dump
```

`scripts\0_kiem_thu_tu_dong.bat` tự sao lưu vào `backups\truoc_kiem_thu.dump` trước khi chạy migration.

## 6. Khi gặp lỗi

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| Google báo `redirect_uri_mismatch` | Redirect URI trên Google khác `PUBLIC_BASE_URL` + `/api/auth/callback` (kể cả `http`/`https`, dấu `/` cuối). |
| Google báo "Access blocked" | Audience **External** + **Testing** mà email chưa có trong **Test users**. |
| Đăng nhập xong quay lại trang đăng nhập | `COOKIE_SECURE=true` khi đang chạy `http://`. |
| Trang báo "Chỉ tài khoản @ictu.edu.vn" | Đăng nhập bằng Gmail cá nhân; chọn lại tài khoản trường. |
| Thao tác báo 403 "CSRF" | Mở giao diện bằng địa chỉ khác `PUBLIC_BASE_URL`. |
| API không khởi động | `docker compose logs api --tail 80`. |
