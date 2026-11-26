# RAG Quiz

Web app sinh câu hỏi trắc nghiệm từ slide bài giảng. Tải lên file PPTX hoặc PDF, hệ thống tự đọc slide và tạo ngân hàng câu hỏi 4 chọn 1. Mỗi câu có giải thích cho từng phương án và trích dẫn slide nguồn. Từ ngân hàng này, người học tạo đề, làm bài, xem lại và hỏi chatbot.

## Tính năng

- **Nạp slide:** đọc text, speaker notes và hình ảnh. Slide có hình được mô tả bằng model thị giác.
- **Sinh ngân hàng câu hỏi:** tự chạy sau khi nạp, có thể sinh thêm theo khoảng slide.
- **Tạo đề:** chọn phạm vi, 10–50 câu và tỉ lệ mức Bloom. Không gọi LLM.
- **Làm bài và xem lại:** chấm điểm thang 10, hiện lý do đúng sai, câu trích chứng minh và ảnh slide.
- **Chatbot:** trả lời có trích dẫn slide, từ chối khi tài liệu không đề cập.
- **Đăng nhập:** chỉ tài khoản Google `@ictu.edu.vn` (OpenID Connect + PKCE, phiên lưu ở server, chống CSRF).
- **Phân quyền tài liệu:** thư viện môn học dùng chung và slide riêng của từng sinh viên (có hạn mức). Trợ lý và tạo đề chỉ dùng slide người dùng được xem.
- **Kết quả của tôi:** điểm theo thời gian, hồ sơ hiểu nhầm, lịch sử làm bài.
- **Quản trị** (email trong `ADMIN_EMAILS`): thống kê cả lớp, quản lý bài giảng, ngân hàng câu hỏi (cả câu bị loại kèm lý do), danh sách sinh viên.

## Công nghệ

| Thành phần | Công nghệ |
| --- | --- |
| Giao diện | React + TypeScript (Vite, Tailwind CSS, TanStack Query), phục vụ bằng nginx |
| Đăng nhập | Google OpenID Connect (Authorization Code + PKCE) xử lý ở backend, phiên trong PostgreSQL |
| Backend | FastAPI, Python 3.11 |
| Cơ sở dữ liệu | PostgreSQL 16 + pgvector |
| LLM | `gpt-6-luna` qua LiteLLM |
| Embedding | `BAAI/bge-m3` (dense + sparse), chạy local |
| Sinh đáp án nhiễu (v2) | ViT5-base tự fine-tune, NLI mDeBERTa-v3, reranker bge-reranker-v2-m3 |
| Xử lý slide | PyMuPDF, python-pptx, LibreOffice |
| Triển khai | Docker Compose |

## Cài đặt và chạy

Cần có Docker và API key OpenAI.

1. Tạo file cấu hình rồi điền `OPENAI_API_KEY`, đổi `POSTGRES_PASSWORD`, và điền phần **Đăng nhập Google**
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ADMIN_EMAILS`, `SESSION_SECRET`; cách lấy xem
   [docs/huong-dan-trien-khai.md](docs/huong-dan-trien-khai.md)):
   ```
   cp .env.example .env
   ```
2. Khởi động:
   ```
   docker compose up -d --build
   ```
3. Mở ứng dụng:

   | Dịch vụ | Địa chỉ |
   | --- | --- |
   | Giao diện | http://localhost:8080 |
   | API docs (chỉ trên máy chủ) | http://localhost:8000/docs |

   Cho sinh viên dùng từ máy khác: cần địa chỉ https, xem [docs/huong-dan-trien-khai.md](docs/huong-dan-trien-khai.md).

Lần đầu xử lý slide sẽ lâu hơn vì phải tải model bge-m3 (khoảng 2,3 GB).

## Luồng hoạt động

```
Upload slide
  → Parse, làm sạch, lọc ảnh, mô tả hình (VLM)
  → Chunk theo slide, embedding bge-m3, lưu vào PostgreSQL
  → Sinh câu hỏi: hạt giống → ngữ cảnh → gpt-6-luna → hậu kiểm bằng luật → chống trùng → lưu
  → Tạo đề → làm bài → chấm điểm → xem lại (+ chatbot)
```

Mỗi câu ứng viên chỉ gọi LLM một lần và không có model thứ hai chấm lại. Model phải chép nguyên văn câu chứng minh đáp án từ slide, và luật kiểm tra câu đó có khớp với slide không. Câu trượt được sinh lại kèm lý do trượt.

## Phiên bản 2: sinh và chọn đáp án nhiễu

Bật bằng `bank.pipeline: v2` trong `config.yaml` (đặt `v1` để quay về cách cũ). Kế hoạch đầy đủ: [docs/ke-hoach-v2.md](docs/ke-hoach-v2.md).

```
1. LLM chọn ý hỏi + đáp án đúng + câu trích nguyên văn      2. LLM viết câu hỏi khi đã biết đáp án
3. ViT5 tự fine-tune sinh 5–8 ứng viên + LLM sinh 2–3 ứng viên kiểu hiểu lầm
4. Luật: bỏ ứng viên chép đáp án đúng, sai hình thức        5. NLI: bỏ ứng viên mà slide chứng minh là đúng
6. Chọn bộ 3 có entropy cao nhất mà đáp án đúng vẫn thắng rõ (δ)
7. LLM viết giải thích từng phương án                       8. Hậu kiểm v1, chống trùng, lưu kèm mọi ứng viên
```

Kỹ thuật lấy từ Chung et al. 2020 (Findings of EMNLP): unlikelihood loss trên token đáp án đúng, quét hệ số loss, lấy ứng viên từ nhiều nguồn, chọn bộ bằng cực đại entropy (thêm ràng buộc δ), đo tỉ lệ chép đáp án.

- **Huấn luyện ViT5:** thư mục `training/`, chạy trên Kaggle bằng `training/notebooks/kaggle_train_ddp.ipynb`. Xem [training/README.md](training/README.md). Giải nén model vào `checkpoints/dg-vit5-stage1/best`. Chưa có checkpoint thì pipeline tự bỏ nguồn ViT5 và chỉ dùng ứng viên của LLM.
- **Database đang có dữ liệu:** chạy một lần `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/002_v2.sql'`.
- **Model tải thêm lần đầu:** NLI `mDeBERTa-v3-base-xnli` và reranker `bge-reranker-v2-m3`.
- **Bảng so sánh C0–C4:** `python -m eval.v2.run_ablation --docs <id bài test> --n-seeds 100`.
- **Bản v1 nguyên trạng:** `legacy/v1/` (chạy song song ở cổng 8001/8502), git tag `v1.0`.

## Cấu trúc thư mục

```
app/
├── api/          # Endpoint FastAPI
├── ingestion/    # Parse slide, lọc ảnh, VLM, chunking
├── retrieval/    # Embedding, tìm kiếm hybrid, rerank
├── generation/   # Sinh câu hỏi (v1, pipeline_v2), ứng viên, bộ lọc, chọn bộ 3, hậu kiểm, tạo đề
├── local_models/ # ViT5, NLI chạy local (v2)
├── chat/         # Chatbot
└── prompts/      # Toàn bộ prompt
web/              # Giao diện React (src/features: study, quiz, chat, results, admin)
e2e/              # Kiểm thử giao diện bằng Playwright (scripts\10_kiem_thu_giao_dien.bat)
ui/               # Giao diện Streamlit cũ (không còn chạy, giữ để tham khảo)
training/         # Fine-tune ViT5 sinh đáp án nhiễu (v2)
checkpoints/      # Model đã fine-tune (không đưa vào git)
eval/             # Script đánh giá (mcq/ của v1, v2/ bảng so sánh)
tests/            # Kiểm thử pipeline v2
migrations/       # Schema database
legacy/v1/        # Bản v1 nguyên trạng
docs/             # Tài liệu và sơ đồ
config.yaml       # Tên model và tham số thuật toán
```

## Cấu hình

- **`.env`:** API key, kết nối database, đường dẫn. Không commit file này.
- **`config.yaml`:** tên model, tên môn học và tham số thuật toán, như số câu mỗi slide (`questions_per_slide`) hay tỉ lệ Bloom (`bloom_mix`).

Sau khi sửa `config.yaml`, chạy `docker compose restart api`. Sau khi sửa code trong `app/` hoặc `web/`, chạy `docker compose up -d --build`.

Các file trong `migrations/` chỉ tự chạy khi volume database còn trống.

## Đánh giá

Đánh giá chất lượng câu hỏi nằm trong `eval/mcq/`, gồm thống kê tự động, phiếu cho 2 người chấm và judge độc lập. Xem hướng dẫn từng bước ở [eval/mcq/README.md](eval/mcq/README.md).

`eval/eval_retrieval.py` và `eval/eval_ragas.py` hiện mới là khung, chưa được cài.

## Tài liệu

- [Tổng quan hệ thống](docs/tong-quan-he-thong.md): chunking, database, quy tắc và prompt sinh câu hỏi, model, output.
- [Sơ đồ luồng hoạt động](docs/so-do-he-thong.html)
- [Kế hoạch phiên bản 2](docs/ke-hoach-v2.md)
- [Hướng dẫn triển khai](docs/huong-dan-trien-khai.md): đăng nhập Google, mở cho máy khác qua https, quản trị, sao lưu.

## Bản v3 (11/2026): câu nhiễu chẩn đoán hiểu nhầm và cá nhân hoá

- **Test hệ thống:** xem `docs/huong-dan-test.md`.
  - Test tự động: nhấp đúp `scripts\0_kiem_thu_tu_dong.bat` (backend), rồi `scripts\10_kiem_thu_giao_dien.bat` (giao diện). Không gọi API nào.
  - Test tay: theo bảng 8 bước trong tài liệu.
- **Đánh giá (Mốc 3):** chạy lần lượt `scripts\1_…` đến `scripts\9_…` (số đầu tên file là thứ tự; file đã chạy xong nằm trong `scripts\_da_chay\`). Thứ tự và ý nghĩa từng file có trong `docs/huong-dan-test.md`.
- **Kế hoạch và thiết kế:** `docs/ke-hoach-v3.md`, `docs/ke-hoach-v3-chi-tiet.md`.
- **Thư mục:**
  - `backups/`: bản sao lưu DB trước mỗi migration.
  - `eval/logs/`: log của các file `.bat`.
  - `_luu_tru/`: đồ cũ, xoá được.
