# Tổng quan hệ thống RAG Quiz

Cập nhật: 01/11/2026 · Mô tả theo code hiện tại trong `app/`, `config.yaml` và `app/prompts/`.

## 1. Tổng quan sản phẩm

RAG Quiz là web app cho **một môn học** (mặc định: Xử lý ngôn ngữ tự nhiên). Giảng viên hoặc người học tải slide bài giảng lên. Hệ thống tự đọc slide, rồi **sinh ngân hàng câu hỏi trắc nghiệm 4 chọn 1** có giải thích cho từng phương án và có trích dẫn slide nguồn. Từ ngân hàng này, người học tạo đề, làm bài, xem điểm, xem lại từng câu kèm ảnh slide gốc và hỏi chatbot khi chưa hiểu.

**Trọng tâm của sản phẩm là khâu sinh câu hỏi.** Hệ thống không dùng LLM thứ hai để chấm lại câu hỏi. Chất lượng câu hỏi được giữ bằng ba lớp:

1. Prompt chặt, có hướng dẫn riêng cho từng mức Bloom và 3 câu mẫu (few-shot).
2. Model phải nêu ý cần hỏi (`key_point`) và **chép nguyên văn câu chứng minh** (`evidence`) từ slide trước khi viết câu hỏi.
3. Hậu kiểm bằng luật (không gọi LLM). Câu trượt được sinh lại, kèm lý do trượt trong prompt.

| Chức năng | Gọi LLM? | Mô tả ngắn |
| --- | --- | --- |
| Nạp slide | Có (VLM, chỉ slide có hình) | PPTX/PDF → text, ảnh, chunk, vector |
| **Sinh ngân hàng câu hỏi** | **Có (1 lần gọi / câu ứng viên)** | Chạy tự động sau khi nạp, hoặc khi bấm "Sinh thêm" |
| Tạo đề | Không | Lấy mẫu từ ngân hàng theo phạm vi và mức Bloom |
| Làm bài, chấm điểm, xem lại | Không | So khớp đáp án, hiện lý do và slide nguồn |
| Chatbot (phần phụ) | Có | Hỏi đáp có trích dẫn slide, từ chối khi tài liệu không đề cập |

**Công nghệ:** FastAPI (backend), Streamlit (giao diện), PostgreSQL 16 + pgvector, bge-m3 chạy local, LiteLLM → OpenAI, Docker Compose.

```
Upload slide
   │
   ▼
[1] Xử lý input: parse → làm sạch → lọc ảnh → VLM mô tả hình
   │
   ▼
[2] Chunking → nhận diện ngôn ngữ → embedding bge-m3 → lưu chunks
   │
   ▼
[3] Sinh ngân hàng câu hỏi: hạt giống → ngữ cảnh → LLM sinh → hậu kiểm luật → chống trùng → lưu
   │
   ▼
[4] Tạo đề → làm bài → chấm điểm → xem lại (+ chatbot)
```

Trạng thái file (`documents.status`): `uploaded → parsing → embedding → generating → ready`. Lỗi ở bất kỳ bước nào thì thành `failed` kèm thông báo lỗi.

---

## 2. Xử lý input

**Đầu vào:** file `.pptx` hoặc `.pdf` cùng số buổi học (`session_no`), gửi qua `POST /documents`. File lưu vào `data/uploads/` với tên ngẫu nhiên. Toàn bộ xử lý chạy nền (FastAPI `BackgroundTasks`).

### 2.1. Parse slide (`ingestion/slide_parser.py`)

| Bước | PPTX | PDF |
| --- | --- | --- |
| Ảnh slide | LibreOffice headless chuyển sang PDF, PyMuPDF render PNG **150 dpi** vào `data/renders/{document_id}/slide_XXX.png` | PyMuPDF render PNG trực tiếp |
| Text | Đọc thẳng từ PPTX bằng `python-pptx`: chữ trong mọi shape (kể cả group), bảng ghép thành dòng `ô | ô | ô`, sắp theo vị trí trên → dưới, trái → phải | PyMuPDF `get_text` |
| Tiêu đề | Placeholder TITLE / CENTER_TITLE | Dòng có cỡ chữ lớn nhất ở nửa trên slide |
| Speaker notes | Có (`python-pptx`) | Không có |
| Slide ẩn | Bỏ qua (LibreOffice cũng không xuất ra PDF) | — |

Text của PPTX được lấy thẳng từ file PPTX, không lấy từ PDF. Lý do: khi LibreOffice thay font, lớp chữ tiếng Việt trong PDF có thể bị vỡ ("một" thành "m t" + "ộ" rời).

### 2.2. Làm sạch text

- **Bỏ header/footer:** dòng xuất hiện ở ≥ 50% số slide (tên trường, tên môn…) bị xoá. Chỉ áp dụng khi file có từ 4 slide trở lên.
- **Bỏ số trang:** dòng chỉ chứa số, như `12` hoặc `12 / 40`.

### 2.3. Lọc ảnh (`ingestion/image_filter.py`)

Mỗi ảnh nhúng trong slide được đánh dấu là ảnh rác nếu:
- chiếm **< 5%** diện tích trang (icon, ảnh nhỏ), hoặc
- cùng một ảnh (cùng hash) xuất hiện ở **≥ 30%** số slide (logo, ảnh nền template).

### 2.4. Mô tả hình bằng VLM (`ingestion/vlm_caption.py`)

- **Khi nào gọi:** slide còn ảnh sau khi lọc, **hoặc** slide có dưới **30 từ** (tính text + notes).
- **Gửi gì:** ảnh PNG của cả slide và text đã trích.
- **Model:** `gpt-6-luna`, nhiệt độ 0, gọi song song tối đa 5 slide cùng lúc.
- Lỗi ở một slide chỉ làm mất mô tả của slide đó, không làm hỏng cả file.

Prompt (`prompts/vlm_caption.txt`):

```text
Mô tả nội dung slide bài giảng trong ảnh để phục vụ tìm kiếm và ra đề.
- Giải thích sơ đồ, biểu đồ, bảng: các thành phần và quan hệ giữa chúng.
- Giữ nguyên thuật ngữ tiếng Anh; viết bằng ngôn ngữ của slide.
- Chỉ mô tả những gì có trong ảnh, KHÔNG suy đoán hay thêm kiến thức ngoài.
- Không lặp lại nguyên văn phần text đã trích dưới đây.

TEXT ĐÃ TRÍCH:
{slide_text}
```

---

## 3. Chunking

Code: `ingestion/chunker.py`. **Đơn vị chunk là slide**, không cắt theo số token.

### 3.1. Quy tắc gộp

Số từ của một slide được tính trên text + notes + mô tả VLM.

| Trường hợp | Xử lý |
| --- | --- |
| Slide trống hoàn toàn (0 từ) | Bỏ |
| Slide đủ dài (≥ 15 từ) | Thành 1 chunk riêng |
| Slide ngắn (< 15 từ), **cùng tiêu đề** với slide liền trước | Gộp vào chunk của slide trước (slide "tiếp theo" của cùng một mục) |
| Slide ngắn, **khác tiêu đề** (thường là slide mở mục) | Gộp vào chunk của slide đủ dài **kế tiếp** |
| Slide ngắn nằm cuối file | Gộp vào chunk cuối cùng |

Chunk gộp ghi `slide_no` (slide đầu) và `slide_end` (slide cuối). Ảnh hiển thị của chunk lấy từ slide có nhiều chữ nhất trong nhóm. Tiêu đề lấy từ slide đầu tiên trong nhóm có tiêu đề.

### 3.2. Các trường text của một chunk

| Trường | Dùng để |
| --- | --- |
| `raw_text` | Hiển thị cho người dùng |
| `notes` | Speaker notes |
| `vlm_caption` | Mô tả hình, tách riêng để làm thí nghiệm có/không VLM |
| `embed_text` | Đưa vào embedding, retrieval và prompt sinh câu hỏi |

```text
embed_text = "[Buổi {session_no} – Slide {slide_no}–{slide_end}] {title}
{raw_text (bỏ dòng đầu nếu trùng tiêu đề)}
{notes}
{vlm_caption}"
```

### 3.3. Sau khi chunk

1. **Nhận diện ngôn ngữ** (`lingua`): `vi`, `en` hoặc `mixed`. Chunk là `mixed` khi ngôn ngữ phụ chiếm ≥ 20% số ký tự.
2. **Embedding** bằng **bge-m3** (chạy local, batch 16), ra cùng lúc:
   - vector dense 1024 chiều;
   - vector sparse (trọng số từ vựng, 250.002 chiều).
3. Ghi vào bảng `chunks`, rồi chuyển sang sinh câu hỏi.

### 3.4. Retrieval hybrid (dùng khi sinh câu hỏi và chatbot)

1. Lọc theo phạm vi: `is_active`, buổi, khoảng slide.
2. Lấy **top 20 dense** (cosine) và **top 20 sparse** (tích vô hướng).
3. Gộp bằng **RRF**: điểm = Σ 1 / (60 + hạng).
4. Rerank bằng bge-reranker-v2-m3 là tuỳ chọn, mặc định tắt.
5. Trả về top k: k = 2 khi sinh câu hỏi, k = 5 khi chat.

Không dùng index HNSW, nên khi có điều kiện lọc vẫn luôn đủ kết quả.

---

## 4. Cơ sở dữ liệu

PostgreSQL 16 + extension `pgvector`. Schema chuẩn nằm ở `migrations/001_init.sql`. Có 8 bảng:

| Bảng | Vai trò | Cột chính |
| --- | --- | --- |
| `documents` | Mỗi file đã upload | `id`, `filename`, `file_path`, `session_no`, `status`, `error`, `is_active` |
| `chunks` | Đơn vị tìm kiếm | `document_id`, `session_no`, `slide_no`, `slide_end`, `title`, `raw_text`, `notes`, `vlm_caption`, `embed_text`, `image_path`, `lang`, `embedding VECTOR(1024)`, `sparse SPARSEVEC(250002)`, `tsv` |
| `questions` | Ngân hàng câu hỏi (cả câu đạt lẫn câu bị loại) | `stem`, `options`, `answer`, `rationales`, `explanation`, `bloom_level`, `source_chunk_ids`, `status`, `validation`, `stem_embedding`, `times_used` |
| `quizzes` | Một đề đã tạo | `scope` (JSONB), `num_questions`, `bloom_mix` |
| `quiz_questions` | Câu hỏi thuộc đề | `quiz_id`, `question_id`, `position` |
| `attempts` | Một lần làm bài | `quiz_id`, `user_name`, `answers` (JSONB), `score` |
| `conversations` | Một phiên chat | `attempt_id`, `question_id` (đều có thể rỗng) |
| `chat_messages` | Từng lượt chat | `conversation_id`, `role`, `content`, `cited_chunk_ids` |

```
documents 1─n chunks
documents 1─n questions ──(source_chunk_ids: mảng id)──► chunks
quizzes   1─n quiz_questions n─1 questions
quizzes   1─n attempts
conversations ─► attempts, questions (tuỳ chọn)
conversations 1─n chat_messages
```

**Quy ước quan trọng:**
- **Không xoá cứng.** Xoá hoặc thay tài liệu thì đặt `is_active = false`. Lý do: `source_chunk_ids` là mảng, không có khoá ngoại, và câu hỏi cũ vẫn cần xem được nguồn.
- `tsv` là cột full-text tự sinh từ `embed_text`, cấu hình `simple`. Không dùng `unaccent`, vì bỏ dấu làm "ma", "mà", "mã" trùng nhau.
- Index: GIN trên `tsv`, `(session_no, slide_no)`, `(document_id)` trên chunks, `(document_id, status)` trên questions.

---

## 5. Sinh câu hỏi trắc nghiệm

Code: `generation/bank_builder.py` và `generation/validator.py`. Prompt: `prompts/mcq_system.txt`, `prompts/mcq_user.txt`, `prompts/mcq_bloom.json`, `prompts/few_shot.json`.

### 5.1. Quy trình cho một file

```
Chunks của file
  │
  ▼
Chọn hạt giống + gán mức Bloom
  │
  ▼  (mỗi hạt giống, chạy song song 5)
Ngữ cảnh = hạt giống + 2 chunk liên quan cùng buổi
  │
  ▼
gpt-6-luna sinh 1 câu (JSON) ──sai JSON/schema──► sinh lại
  │
  ▼
Hậu kiểm luật: source_ids → form → evidence ──trượt──► lưu rejected, sinh lại kèm lý do
  │
  ▼
Chống trùng (embedding) ──trùng──► lưu rejected, sinh lại kèm lý do
  │
  ▼
Xáo đáp án → lưu accepted → đủ mục tiêu thì dừng
```

**Mục tiêu và hạt giống:**
- Số câu đạt mục tiêu = số slide × **0,5**. Ví dụ 40 slide → 20 câu.
- Số hạt giống = mục tiêu × **1,5** (sinh dư để bù câu bị loại).
- Hạt giống là chunk có ≥ **30 từ**, chọn rải đều theo thứ tự slide để phủ toàn bài.
- Mức Bloom chia theo tỉ lệ **remember 40% · understand 40% · apply 20%**, rồi xáo ngẫu nhiên giữa các hạt giống.

**Ngữ cảnh:** chunk hạt giống cộng 2 chunk liên quan nhất trong cùng buổi, tìm bằng retrieval hybrid. Chunk hạt giống được đánh dấu `vai_trò="hạt giống"` trong prompt.

**Sinh lại:**
- Mỗi hạt giống được thử tối đa **3 lần** (1 lần đầu + 2 lần sinh lại).
- Lần sinh lại có thêm đoạn "LẦN TRƯỚC CÂU HỎI BỊ LOẠI VÌ: …" trong prompt.
- Mọi câu ứng viên đều được lưu, cả `accepted` lẫn `rejected`, để phục vụ đánh giá.

### 5.2. Quy tắc cho một câu hỏi tốt

Các quy tắc này nằm trong prompt. Phần lớn được kiểm lại bằng luật ở mục 5.4.

**Nội dung**
- Chỉ dùng kiến thức trong ngữ cảnh, không thêm kiến thức ngoài.
- Mỗi câu kiểm tra **một** ý quan trọng: khái niệm, cơ chế, so sánh, quy trình, công thức, ưu hoặc nhược điểm.
- Không hỏi chi tiết vụn vặt như tên ví dụ, năm, tác giả hay số slide.
- Câu hỏi phải tự đứng được, vì người làm bài không thấy ngữ cảnh. Không viết "theo đoạn trên", "trong ngữ cảnh".
- Ý trong slide mơ hồ thì chọn ý khác rõ ràng hơn để hỏi.

**Đáp án**
- Đúng 4 phương án, đúng 1 phương án đúng, và phương án đúng phải khớp với `evidence`.
- 3 phương án sai phải cùng loại và cùng cấu trúc ngữ pháp với đáp án đúng. Có thể lấy từ:
  - khái niệm gần giống trong ngữ cảnh;
  - hiểu lầm phổ biến của sinh viên;
  - thay hoặc đảo một chi tiết quan trọng.
- Mỗi phương án sai phải **sai rõ ràng** theo ngữ cảnh, không "đúng một phần".
- 4 phương án dài tương đương.
- Từ khoá của câu hỏi không được chỉ xuất hiện ở đáp án đúng.
- Không dùng "luôn luôn", "không bao giờ" làm dấu hiệu nhận ra phương án sai.
- Cấm "tất cả đều đúng/sai" và "không có phương án nào đúng". Cấm phủ định kép.
- Không nhắc chữ cái A/B/C/D ở bất kỳ đâu, vì thứ tự phương án sẽ được xáo.

**Theo mức Bloom** (`prompts/mcq_bloom.json`)

| Mức | Kiểm tra | Dạng gợi ý |
| --- | --- | --- |
| `remember` | Nhớ lại kiến thức nêu trực tiếp: định nghĩa, thuật ngữ, thành phần, mục đích. Phải diễn đạt lại, không chép nguyên câu slide. | "X là gì?", "Thành phần nào thuộc X?", "Mục đích chính của X là gì?" |
| `understand` | Hiểu bản chất: giải thích vì sao, phân biệt hai khái niệm, nhận ra ví dụ đúng, suy ra hệ quả. Đáp án đúng suy ra được từ ngữ cảnh nhưng không trùng nguyên văn slide. | "Vì sao X…?", "Khác biệt chính giữa X và Y?", "Trường hợp nào là ví dụ của X?" |
| `apply` | Vận dụng vào tình huống **mới**: câu văn mẫu, tập dữ liệu nhỏ, số liệu đơn giản. Mọi dữ kiện nằm trong câu hỏi. Có tính toán thì tự tính lại từng bước. Phương án sai là kết quả của lỗi thường gặp (quên một bước, nhầm công thức, đảo tử/mẫu). Hạt giống không có công thức thì hỏi chọn phương pháp phù hợp nhất cho một bài toán. | Bài toán tính IDF, chọn kỹ thuật cho tình huống cụ thể |

### 5.3. Prompt

Mỗi lần gọi gồm một system prompt và một user prompt. Model trả về **chế độ JSON**, nhiệt độ **0,7**.

**System** (`prompts/mcq_system.txt`)

```text
Bạn là giảng viên môn {course_name}, chuyên ra đề trắc nghiệm 4 lựa chọn cho sinh viên đại học.

Nguyên tắc bắt buộc:
- Chỉ dùng kiến thức có trong NGỮ CẢNH. Không thêm kiến thức ngoài, không suy diễn vượt quá điều slide nói.
- Mỗi câu kiểm tra MỘT ý quan trọng của bài: khái niệm, cơ chế, so sánh, quy trình, công thức, ưu/nhược điểm. Không hỏi chi tiết vụn vặt (tên ví dụ minh hoạ, năm, tên tác giả, số thứ tự slide) trừ khi slide nhấn mạnh.
- Viết tiếng Việt tự nhiên, rõ ràng; giữ nguyên thuật ngữ chuyên ngành tiếng Anh.
- Người làm bài KHÔNG nhìn thấy ngữ cảnh: câu hỏi phải tự đứng được, không viết "theo đoạn trên", "trong ngữ cảnh", "chunk".
- Không có ai chấm lại câu hỏi của bạn, nên bạn phải tự chắc chắn: đúng 1 phương án đúng theo ngữ cảnh, 3 phương án còn lại chắc chắn sai theo ngữ cảnh. Nếu một ý trong slide mơ hồ, hãy chọn ý khác rõ ràng hơn để hỏi.

Chỉ trả về một object JSON, không kèm giải thích bên ngoài.
```

**User** (`prompts/mcq_user.txt`)

```text
VÍ DỤ CÂU HỎI TỐT (chỉ để tham khảo định dạng và chất lượng, KHÔNG lấy nội dung ví dụ):
{few_shot}

NGỮ CẢNH:
{context}

NHIỆM VỤ: Viết 1 câu hỏi mức Bloom "{bloom_level}" về chunk hạt giống (id={seed_id}, có vai_trò="hạt giống"). Các chunk khác chỉ để bổ trợ và để lấy ý cho phương án sai.

Yêu cầu riêng cho mức "{bloom_level}":
{bloom_guide}

Làm lần lượt các bước sau và ghi kết quả vào JSON theo đúng thứ tự:
1. key_point: một câu nêu ý kiến thức sẽ kiểm tra (lấy từ chunk hạt giống).
2. evidence: chép NGUYÊN VĂN 1–2 câu từ NGỮ CẢNH chứng minh đáp án đúng. Sao chép đúng từng chữ, không diễn đạt lại, không gộp các câu ở xa nhau. Nếu không tìm được câu nào chứng minh, đổi sang ý khác.
3. stem: câu hỏi rõ ràng, hỏi một ý, tự đứng được; diễn đạt lại chứ không chép nguyên câu slide; không phủ định kép. Nếu buộc phải hỏi phủ định thì viết hoa chữ KHÔNG.
4. options: đúng 4 phương án.
   - Đúng 1 phương án đúng, khớp với evidence.
   - 3 phương án sai: cùng loại và cùng cấu trúc ngữ pháp với đáp án đúng; lấy từ khái niệm gần giống trong ngữ cảnh, hiểu lầm phổ biến của sinh viên, hoặc thay/đảo một chi tiết quan trọng. Mỗi phương án sai phải SAI rõ ràng theo ngữ cảnh, không được "đúng một phần".
   - 4 phương án dài tương đương (chênh không quá vài từ); từ khoá của stem không chỉ xuất hiện ở đáp án đúng; không dùng "luôn luôn", "không bao giờ" làm dấu hiệu nhận ra phương án sai.
   - Cấm "tất cả đều đúng/sai", "không có phương án nào đúng".
   - rationale: 1 câu giải thích vì sao phương án đó đúng hoặc sai, dựa trên ngữ cảnh.
5. explanation: 1–3 câu tóm tắt kiến thức cần nhớ.
6. bloom_level: "{bloom_level}".
7. source_chunk_ids: id các chunk đã dùng, bắt buộc có {seed_id}.
Không nhắc chữ cái A/B/C/D ở bất kỳ đâu (thứ tự phương án sẽ được xáo).

KHÔNG trùng ý với các câu đã có:
{existing_stems}
{feedback}
Trả về DUY NHẤT một object JSON theo đúng định dạng: { ... }
```

**Các biến được điền vào prompt**

| Biến | Nội dung |
| --- | --- |
| `{few_shot}` | 3 câu mẫu trong `few_shot.json`, ưu tiên câu cùng mức Bloom với hạt giống. Hiện có 3 câu: Bag-of-Words (remember), TF-IDF (understand), tính IDF (apply). |
| `{context}` | Các chunk dạng `<chunk id=… nguồn="Slide buổi X, slide Y" vai_trò="hạt giống">embed_text</chunk>` |
| `{bloom_guide}` | Hướng dẫn của mức Bloom tương ứng trong `mcq_bloom.json` |
| `{existing_stems}` | Tối đa 30 câu hỏi đã đạt trong cùng buổi, để tránh trùng ý |
| `{feedback}` | Rỗng ở lần đầu; ở lần sinh lại là lý do trượt của lần trước |

### 5.4. Hậu kiểm bằng luật (không gọi LLM)

Các bước chạy lần lượt và dừng ở bước trượt đầu tiên. Kết quả từng bước ghi vào `questions.validation`.

| Bước | Luật | Lý do trượt (`rule`) |
| --- | --- | --- |
| 0. Schema (Pydantic) | Đúng 4 phương án, không rỗng, không trùng nhau, đúng 1 phương án đúng | JSON hỏng: không lưu, sinh lại |
| 1. `source_ids` | `source_chunk_ids` chỉ chứa id có trong ngữ cảnh và phải có id hạt giống | `outside_context`, `seed_missing` |
| 2. `form` | Cấm cụm "tất cả đều đúng/sai", "none of the above"… | `banned_phrase` |
| | Không có ≥ 2 từ phủ định trong câu hỏi | `double_negation` |
| | Không trỏ tới "ngữ cảnh đã cho", "đoạn trên", "chunk id", "hạt giống"… | `context_reference` |
| | Đáp án đúng không dài hơn 1,5 lần độ dài trung bình đáp án sai **và** hơn 4 từ | `correct_too_long` |
| | Đáp án đúng (≥ 3 từ) không nằm nguyên văn trong câu hỏi | `answer_in_stem` |
| | Không nhắc "đáp án A", "phương án B"… | `letter_reference` |
| 3. `evidence` | `evidence` ≥ 4 từ và **khớp nguyên văn ≥ 85%** với một chunk trong ngữ cảnh (so trên text đã chuẩn hoá NFC, chữ thường, bỏ dấu câu; chỉ tính đoạn khớp liên tục ≥ 8 ký tự) | `too_short`, `not_verbatim` |
| 4. Chống trùng | Cosine giữa embedding (câu hỏi + đáp án đúng) và câu `accepted` gần nhất (mọi tài liệu đang hoạt động) phải ≤ **0,9**. Bước này chạy trong khoá để hai câu sinh song song không cùng lọt. | `duplicate` |

Bước `evidence` thay cho bước chấm lại bằng LLM (groundedness). Nếu model bịa kiến thức ngoài slide, nó không chép được câu chứng minh nguyên văn từ slide, nên câu bị loại.

### 5.5. Xáo đáp án và lưu

- LLM không dùng chữ cái A–D. Sau khi qua kiểm, hệ thống **xáo ngẫu nhiên** thứ tự 4 phương án rồi mới gán A–D, nên `rationale` và `explanation` luôn khớp.
- `bloom_level` lưu là mức yêu cầu. Mức mà LLM tự ghi được lưu trong `validation.llm_bloom_level`.

---

## 6. Tạo đề và làm bài

**Tạo đề** (`generation/quiz_sampler.py`, không gọi LLM)

1. Người học chọn phạm vi (bài, buổi, khoảng slide), số câu (**10–50**) và tỉ lệ Bloom. Không chọn tỉ lệ thì dùng tỉ lệ mặc định 40/40/20.
2. Lấy các câu `accepted` có chunk nguồn nằm trong phạm vi.
3. Chọn câu:
   - nếu đề gồm nhiều bài, chia số câu theo tỉ lệ số câu mỗi bài đang có;
   - trong mỗi bài, chia theo mức Bloom;
   - trong mỗi mức, xoay vòng theo slide nguồn để phủ đều, ưu tiên câu ít được dùng (`times_used` thấp).
4. Mức nào thiếu câu thì bù từ mức khác. Ngân hàng không đủ thì tạo đề với số câu hiện có.
5. Xáo thứ tự câu, lưu đề và tăng `times_used`.

**Làm bài:** đề gửi về giao diện **không kèm đáp án**. Người học phải trả lời hết mới nộp được. Server chấm bằng so khớp, ra số câu đúng và điểm thang 10.

**Xem lại:** với mỗi câu, hệ thống hiện:
- đáp án đã chọn và đáp án đúng;
- lý do đúng hoặc sai của từng phương án, kèm giải thích chung;
- câu trích `evidence` và slide chứa câu trích đó;
- ảnh slide nguồn.

**Chatbot (phần phụ):**
- Mỗi lượt: viết lại câu hỏi nối tiếp → retrieve (≤ 7 chunk) → trả lời có trích dẫn `[n]`.
- Khi hỏi tự do mà điểm dense cao nhất < 0,35, trả lời ngay "tài liệu không đề cập", không gọi LLM.

---

## 7. Mô hình dùng cho từng dịch vụ

Tên model khai báo trong `config.yaml` theo vai trò và gọi qua `llm_client.py` (LiteLLM). Đổi model không cần sửa code.

| Dịch vụ | Vai trò trong config | Model | Chạy ở | Tham số |
| --- | --- | --- | --- | --- |
| Mô tả slide có hình | `vlm` | `gpt-6-luna` | OpenAI API | nhiệt độ 0 |
| **Sinh câu hỏi** | `mcq_generator` | `gpt-6-luna` | OpenAI API | nhiệt độ 0,7, JSON mode, 5 lượt song song |
| Hậu kiểm câu hỏi | — | **Không dùng LLM** (luật + bge-m3 chống trùng) | Local | — |
| Embedding (chunk, câu hỏi, query) | `embedding` | `BAAI/bge-m3` (dense + sparse) | Local | batch 16 |
| Rerank (thí nghiệm) | `reranker` | `BAAI/bge-reranker-v2-m3` | Local | mặc định tắt |
| Chatbot: viết lại câu hỏi | `chat_rewriter` | `gpt-6-luna` | OpenAI API | |
| Chatbot: trả lời | `chat_answer` | `gpt-6-luna` | OpenAI API | nhiệt độ 0,2 |
| Đánh giá (RAGAS / judge) | `judge` | `gpt-6-sol` | OpenAI API | chỉ chạy offline trong `eval/` |
| Judge đánh giá MCQ | `judge_independent` | `gpt-6-sol` | OpenAI API | chỉ chạy offline trong `eval/mcq/`, nhiệt độ 0 |
| Nhận diện ngôn ngữ | — | `lingua` | Local | |

Giá tham khảo (USD / 1M token, vào / ra): `gpt-6-luna` 0,10 / 0,50; `gpt-6-sol` 2 / 10. Pipeline sinh câu hỏi chỉ dùng luna, mỗi câu ứng viên tốn **1 lần gọi**.

---

## 8. Output

### 8.1. Output của LLM khi sinh 1 câu hỏi

```json
{
  "key_point": "IDF giảm trọng số của từ xuất hiện trong nhiều văn bản.",
  "evidence": "IDF đo mức độ hiếm của một từ trong toàn bộ tập văn bản: từ xuất hiện trong càng nhiều văn bản thì IDF càng nhỏ.",
  "stem": "Vì sao trong TF-IDF, các từ phổ biến như \"là\", \"của\" thường nhận trọng số thấp?",
  "options": [
    {"text": "Vì chúng xuất hiện trong hầu hết văn bản của tập dữ liệu", "is_correct": true,  "rationale": "Từ có mặt trong nhiều văn bản có IDF nhỏ, kéo trọng số TF-IDF xuống."},
    {"text": "Vì chúng có tần suất thấp trong từng văn bản",           "is_correct": false, "rationale": "Ngược lại, các từ này thường có TF cao trong từng văn bản."},
    {"text": "Vì chúng bị loại khỏi từ điển ở bước tách từ",           "is_correct": false, "rationale": "Tách từ không loại từ; trọng số thấp đến từ IDF."},
    {"text": "Vì chúng có độ dài ngắn hơn các từ khác",                "is_correct": false, "rationale": "TF-IDF không phụ thuộc vào độ dài của từ."}
  ],
  "explanation": "Trọng số TF-IDF là tích của TF và IDF; từ xuất hiện ở hầu hết văn bản có IDF gần 0 nên ít giá trị phân biệt.",
  "bloom_level": "understand",
  "source_chunk_ids": [102]
}
```

### 8.2. Một câu hỏi lưu trong ngân hàng (`questions`)

| Trường | Ví dụ / ý nghĩa |
| --- | --- |
| `stem` | Câu hỏi |
| `options` | `{"A": "...", "B": "...", "C": "...", "D": "..."}`, đã xáo |
| `answer` | `"C"` |
| `rationales` | `{"A": "vì sao sai", ..., "C": "vì sao đúng"}` |
| `explanation` | Tóm tắt kiến thức |
| `bloom_level` | `remember`, `understand` hoặc `apply` |
| `source_chunk_ids` | `[102, 98]`, dùng để hiện slide nguồn |
| `status` | `accepted` hoặc `rejected` |
| `validation` | Kết quả từng bước kiểm (xem dưới) |
| `stem_embedding` | Vector dùng chống trùng |
| `times_used` | Số đề đã dùng câu này |

```json
{
  "source_ids": {"passed": true, "reason": null, "details": {}},
  "form":       {"passed": true, "reason": null, "details": {}},
  "evidence":   {"passed": true, "reason": null, "details": {"coverage": 1.0, "chunk_id": 102}},
  "duplicate":  {"passed": true, "reason": null, "details": {"max_similarity": 0.71}},
  "attempt": 0,
  "feedback_used": null,
  "llm_bloom_level": "understand",
  "key_point": "IDF giảm trọng số của từ xuất hiện trong nhiều văn bản.",
  "evidence_text": "IDF đo mức độ hiếm của một từ ..."
}
```

### 8.3. Output của API

| Endpoint | Trả về |
| --- | --- |
| `POST /documents`, `GET /documents/{id}` | `id`, `filename`, `session_no`, `status`, `error`, `num_chunks`, `num_accepted`, `num_rejected`, `num_slides` |
| `POST /documents/{id}/questions/generate` | Như trên; chạy nền, trạng thái chuyển sang `generating` |
| `POST /search` | Danh sách chunk: `chunk_id`, buổi, slide, `title`, `raw_text`, `image_path`, `score`, `dense_score` |
| `POST /quizzes`, `GET /quizzes/{id}` | `quiz_id`, `num_requested`, `num_questions`, danh sách câu (`question_id`, `position`, `bloom_level`, `stem`, `options`), **không có đáp án** |
| `POST /attempts` | `attempt_id`, `num_correct`, `num_questions`, `score_10` |
| `GET /attempts/{id}/review` | `score_10` và với mỗi câu: `stem`, `options`, `chosen`, `answer`, `is_correct`, `rationales`, `explanation`, `bloom_level`, `sources` (slide nguồn + `image_url`), `evidence`, `evidence_slide_no` |
| `POST /chat` | Câu trả lời stream (NDJSON), `conversation_id`, danh sách trích dẫn |
| `GET /chunks/{id}/image` | Ảnh PNG của slide nguồn |

---

## 9. Tham số cấu hình chính (`config.yaml`)

| Nhóm | Tham số | Giá trị |
| --- | --- | --- |
| Nạp slide | `render_dpi` / `vlm_min_words` | 150 / 30 |
| | `image_min_area_ratio` / `image_repeat_ratio` | 0,05 / 0,3 |
| | `header_repeat_ratio` / `merge_min_words` | 0,5 / 15 |
| Retrieval | `top_n` / `k` / `rrf_k` / `rerank` | 20 / 5 / 60 / false |
| Ngân hàng câu hỏi | `questions_per_slide` / `oversample` | 0,5 / 1,5 |
| | `bloom_mix` | remember 0,4 · understand 0,4 · apply 0,2 |
| | `min_seed_words` / `context_k` / `concurrency` | 30 / 2 / 5 |
| | `max_retries` / `dedup_threshold` | 2 / 0,9 |
| Chatbot | `history_turns` / `max_context_chunks` / `min_dense_score` | 4 / 7 / 0,35 |

---

## 10. Ghi chú về hiện trạng

- `groundedness.txt` đã xoá vì bước chấm lại bằng LLM đã bỏ.
- `prompts/answerability.txt` giữ lại cho đánh giá offline: judge (`models.judge_independent`) làm lại câu `accepted` trong `eval/mcq/`. Pipeline sinh câu hỏi không nạp file này.
- `thiet-ke-mvp-rag-quiz.md` và comment trong `config.yaml` đã cập nhật khớp với code (01/11/2026).
- Sơ đồ luồng hoạt động: `docs/so-do-he-thong.html`.
- Đánh giá chất lượng câu hỏi: xem hướng dẫn từng bước ở `eval/mcq/README.md`. Đánh giá retrieval và chatbot (`eval/eval_retrieval.py`, `eval/eval_ragas.py`) chưa được cài.
