# RAG Quiz

Web app sinh câu hỏi trắc nghiệm từ slide bài giảng. Tải lên file PPTX hoặc PDF, hệ thống tự đọc slide và tạo ngân hàng câu hỏi 4 chọn 1. Mỗi câu có giải thích cho từng phương án và trích dẫn slide nguồn. Từ ngân hàng này, người học tạo đề, làm bài, xem lại và hỏi chatbot.

## Tính năng

- **Nạp slide:** đọc text, speaker notes và hình ảnh. Slide có hình được mô tả bằng model thị giác.
- **Sinh ngân hàng câu hỏi:** tự chạy sau khi nạp, có thể sinh thêm theo khoảng slide.
- **Tạo đề:** chọn phạm vi, 10–50 câu và tỉ lệ mức Bloom. Không gọi LLM.
- **Làm bài và xem lại:** chấm điểm thang 10, hiện lý do đúng sai, câu trích chứng minh và ảnh slide.
- **Chatbot:** trả lời có trích dẫn slide, từ chối khi tài liệu không đề cập.

## Công nghệ

| Thành phần | Công nghệ |
| --- | --- |
| Giao diện | Streamlit |
| Backend | FastAPI, Python 3.11 |
| Cơ sở dữ liệu | PostgreSQL 16 + pgvector |
| LLM | `gpt-6-luna` qua LiteLLM |
| Embedding | `BAAI/bge-m3` (dense + sparse), chạy local |
| Xử lý slide | PyMuPDF, python-pptx, LibreOffice |
| Triển khai | Docker Compose |

## Cài đặt và chạy

Cần có Docker và API key OpenAI.

1. Tạo file cấu hình rồi điền `OPENAI_API_KEY` và đổi `POSTGRES_PASSWORD`:
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
   | Giao diện | http://localhost:8501 |
   | API docs | http://localhost:8000/docs |

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

## Cấu trúc thư mục

```
app/
├── api/          # Endpoint FastAPI
├── ingestion/    # Parse slide, lọc ảnh, VLM, chunking
├── retrieval/    # Embedding, tìm kiếm hybrid, rerank
├── generation/   # Sinh câu hỏi, hậu kiểm, tạo đề
├── chat/         # Chatbot
└── prompts/      # Toàn bộ prompt
ui/               # Giao diện Streamlit
eval/             # Script đánh giá
migrations/       # Schema database
docs/             # Tài liệu và sơ đồ
config.yaml       # Tên model và tham số thuật toán
```

## Cấu hình

- **`.env`:** API key, kết nối database, đường dẫn. Không commit file này.
- **`config.yaml`:** tên model, tên môn học và tham số thuật toán, như số câu mỗi slide (`questions_per_slide`) hay tỉ lệ Bloom (`bloom_mix`).

Sau khi sửa `config.yaml`, chạy `docker compose restart api`. Sau khi sửa code trong `app/` hoặc `ui/`, chạy `docker compose up -d --build`.

File `migrations/001_init.sql` chỉ tự chạy khi volume database còn trống.

## Đánh giá

Đánh giá chất lượng câu hỏi nằm trong `eval/mcq/`, gồm thống kê tự động, phiếu cho 2 người chấm và judge độc lập. Xem hướng dẫn từng bước ở [eval/mcq/README.md](eval/mcq/README.md).

`eval/eval_retrieval.py` và `eval/eval_ragas.py` hiện mới là khung, chưa được cài.

## Tài liệu

- [Tổng quan hệ thống](docs/tong-quan-he-thong.md): chunking, database, quy tắc và prompt sinh câu hỏi, model, output.
- [Sơ đồ luồng hoạt động](docs/so-do-he-thong.html)
- [Thiết kế MVP](thiet-ke-mvp-rag-quiz.md)
