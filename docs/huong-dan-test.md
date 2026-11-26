# Hướng dẫn test hệ thống (bản v3, 15/11/2026)

## Điều quan trọng nhất: test hệ thống KHÔNG dùng Gemini

| Phần | Dùng API nào | Có bị giới hạn Gemini không? |
|---|---|---|
| Sinh câu hỏi, chatbot, gắn nhãn hiểu nhầm | **OpenAI** (`config.yaml` → `models`) | **Không** |
| Giao diện: làm bài, luyện điểm yếu, chẩn đoán, chọn mức độ khó | Không gọi API nào (dữ liệu đã có trong DB) | **Không** |
| Test tự động (`scripts\0_kiem_thu_tu_dong.bat`) | Không gọi API nào | **Không** |
| **Chỉ** bước chấm chất lượng bằng mô hình (lớp S/J) và đối chứng LLM-Gemini | OpenAI (có trần chi phí) và Gemini miễn phí | Gemini có: hết hạn mức ngày thì tự dừng, hôm sau chạy lại tự tiếp tục |

Vì vậy cứ test thoải mái, không lo hết hạn mức Gemini. Mỗi câu hỏi mới sinh từ slide tốn khoảng 0,003 USD OpenAI. Làm bài và luyện tập không tốn gì.

Muốn bỏ hẳn giới hạn Gemini: vào Google AI Studio, chọn API key đang dùng, bấm **Set up billing**. Chi phí khoảng 2–5 USD cho toàn bộ lần chấm.

## Bước 1: test tự động (5–10 phút, không tốn tiền)

1. Mở **Docker Desktop**, chờ hiện "Engine running".
2. Nhấp đúp **`scripts\0_kiem_thu_tu_dong.bat`**. File này lần lượt:
   - build lại hệ thống;
   - sao lưu DB vào `backups\truoc_kiem_thu.dump`;
   - chạy migration 004 (nếu đã chạy rồi thì không thay đổi gì);
   - chạy 27 test.
3. Kết quả mong đợi: `27 passed` và dòng **"TAT CA TEST DEU QUA"**.

Các test chạy trên DB thật: tự tạo dữ liệu thử có tiền tố `__test_` rồi tự xoá sau khi xong. Phạm vi test:

| Nhóm | Kiểm tra gì |
|---|---|
| Pipeline sinh câu nhiễu | Lọc ứng viên, gắn nhãn hiểu nhầm, chọn bộ 3 đa dạng loại lỗi, cân bằng độ dài đáp án đúng |
| Người học | Nộp bài, hồ sơ hiểu nhầm, đề luyện điểm yếu, chia mức độ khó |
| Đăng nhập, phân quyền | Google OIDC (token giả mạo, sai tên miền, sai nonce/state), phiên, CSRF, hạn mức, slide riêng không lộ sang người khác, API quản trị |
| Thử nghiệm sinh viên | 6 sinh viên ảo đi đủ 3 bước, khảo sát, phân tích, đóng thử nghiệm |
| Bộ đánh giá | Solver và giám khảo bỏ qua các lần gọi lỗi, dừng khi hết hạn mức ngày, phiếu chấm người, chọn lại bộ 3 |

## Bước 2: test giao diện

**Tự động (khoảng 3 phút, lần đầu lâu hơn vì tải image Playwright):** nhấp đúp `scripts\10_kiem_thu_giao_dien.bat`. Trình duyệt Chromium chạy trong Docker, tự tạo 2 tài khoản thử, đi qua đăng nhập, xem slide, làm bài, tải lại trang giữa bài, xem lại, trang kết quả, trang quản trị, rồi xoá dữ liệu thử. Không gọi LLM.

**Bằng tay (khoảng 15 phút):** mở **http://localhost:8080**.

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Bấm **Đăng nhập bằng Google**, chọn tài khoản `@ictu.edu.vn` | Vào trang Học tập, góc phải có tên và ảnh của bạn |
| 2 | Thử đăng nhập bằng Gmail cá nhân | Bị từ chối, hiện thông báo chỉ nhận `@ictu.edu.vn` |
| 3 | Chọn 1 bài ở cột trái, dùng phím ← → | Slide chuyển, URL đổi theo |
| 4 | Cột phải **Trắc nghiệm**: chọn mức **Khó**, 10 câu, **Bắt đầu làm bài** | Slide tạm ẩn, đồng hồ chạy, phím A–D chọn đáp án |
| 5 | Làm vài câu rồi tải lại trang (F5) | Vẫn ở đúng câu, các đáp án đã chọn còn nguyên |
| 6 | Cố tình chọn sai vài câu, **Nộp bài** | Câu sai có **"Có thể bạn đang nhầm: …"**, lời giải thích, trích dẫn |
| 7 | Bấm **Xem trên slide** | Mở đúng slide, câu trích dẫn được tô vàng |
| 8 | Bấm **Hỏi trợ lý về câu này**, chọn một gợi ý | Trợ lý trả lời dần từng chữ, có [1] bấm được để mở slide nguồn (gọi OpenAI) |
| 9 | **Kết quả của tôi** | Có biểu đồ điểm, chỗ hay nhầm, lịch sử; **Xem lại** mở lại bài cũ |
| 10 | **Tải slide** ở cột trái, chọn một file PDF nhỏ | Bài vào mục *Slide của tôi*, hiện các bước xử lý (gọi OpenAI để sinh câu hỏi) |
| 11 | Đăng nhập bằng email quản trị → **Quản trị** | Tổng quan cả lớp, bảng bài giảng, ngân hàng câu hỏi, danh sách sinh viên |

Thử luồng thử nghiệm sinh viên (khung **Thử nghiệm hệ thống ôn tập**): chạy `scripts\7_thu_nghiem_sv_chuan_bi.bat`, rồi ghi email `@ictu.edu.vn` (hoặc phần trước `@`) của người thử vào mục `members` trong `eval\student\data\thu_nghiem.json`. Thử xong chạy `scripts\9_thu_nghiem_sv_dong.bat`. Chi tiết trong `eval\student\kich_ban_thu_nghiem.md`.

## Bước 3: đánh giá chất lượng (đánh giá, không phải test chức năng)

Số đầu tên file là thứ tự chạy. Các file đã chạy xong một lần (tạo bộ NLP, chọn lại V3, chấm Gemini, chạy thử chi phí) nằm trong `scripts\_da_chay\`; không cần chạy lại.

| File | Khi nào | Dùng API |
|---|---|---|
| `scripts\0_kiem_thu_tu_dong.bat` | Khi muốn kiểm tra hệ thống (backend) | Không |
| `scripts\10_kiem_thu_giao_dien.bat` | Sau file 0: kiểm tra giao diện | Không |
| `scripts\1_sinh_doi_chung_llm.bat` | Một lần: sinh đối chứng LLM-GPT, LLM-Gemini; chấm lớp A + E | OpenAI ≤ 0,08 USD + Gemini miễn phí |
| `scripts\2_cham_openai.bat` | Sau file 1: lớp S + J cho V3 và LLM-GPT | OpenAI, trần 1,70 USD |
| `scripts\3_bao_cao_tong_hop.bat`, `4_xuat_cau_hoi_excel.bat` | Bất cứ lúc nào | Không |
| `scripts\5_tao_phieu_cham_nguoi.bat` → `6_phan_tich_phieu_nguoi.bat` | Khi có 2 người chấm | Không |
| `scripts\7_thu_nghiem_sv_chuan_bi.bat` → `8_thu_nghiem_sv_phan_tich.bat` → `9_thu_nghiem_sv_dong.bat` | Khi có buổi thử nghiệm với sinh viên | OpenAI (vài cent, chỉ ở file 7) |

Log của mọi file `.bat` nằm trong `eval\logs\`. Bản sao lưu DB nằm trong `backups\`.
