# Kế hoạch v3: chi tiết từng nhóm việc

Cập nhật: 14/11/2026 · Đi kèm [ke-hoach-v3.md](ke-hoach-v3.md) (mục tiêu, chỉ tiêu, danh sách việc).

Mỗi nhóm gồm: mục tiêu, phụ thuộc, các bước làm (kèm phác thảo code khi cần), kiểm thử và tiêu chí nghiệm thu. Phác thảo code viết theo cấu trúc hiện có của dự án và chỉ là hướng làm, chưa chạy thử.

```text
Phụ thuộc giữa các nhóm

A ──► B ──► G1–G3
│     │
│     └──► C ──► D1–D6 ──► G4–G5 ──► E ──► D7–D8
│                                     │
└─────────────────────────────────────┴──► F ──► G6
```

---

## Nhóm A: Đo lại và sửa lỗi nền

**Mục tiêu:** biết chắc pipeline v2 đang chạy đúng như thiết kế trước khi xây thêm. Có số liệu nền đáng tin để so sánh.

**Phụ thuộc:** không.

### A1. Tìm vì sao ViT5 không sinh ứng viên

**Những gì đã biết từ kết quả 06/11:**

- C2 (chỉ dùng ViT5): 59/60 hạt giống trượt ở bước `selection`, mỗi hạt giống chỉ mất khoảng 10 giây. Vậy ViT5 hoặc không sinh gì, hoặc mọi ứng viên của nó bị lọc hết.
- C4: không có ứng viên `source=vit5` nào trong 183 ứng viên.
- Lần chạy đó chưa ghi `warnings` và `details.pool` (đã thêm vào `run_ablation.py` sau này), nên không phân biệt được hai khả năng trên.

**Các khả năng cần loại trừ, theo thứ tự:**

1. `vit5_available()` trả `False`: thiếu `checkpoints/dg-vit5-stage1/best/config.json` trong container, do mount sai hoặc giải nén sai thư mục.
2. Nạp model lỗi: tokenizer (đã có fallback), hết RAM khi chạy CPU, hoặc phiên bản `transformers`. Lỗi bị nuốt ở `except Exception` trong `from_vit5`, chỉ để lại `log.warning`.
3. Model sinh được nhưng toàn câu rỗng, lặp, hoặc chép đáp án, nên bị lọc ở `form`/`copy`.
4. Bị lọc ở NLI.

**Các bước:**

1. Viết script `eval/v2/diagnose_vit5.py`, chạy trong container (`docker compose exec api python -m eval.v2.diagnose_vit5 --n 10`):

```python
# Phác thảo
from app.local_models import vit5_available, get_generator
from app.generation import filters
from app.generation.candidates import Candidate, dedupe

print("checkpoint:", get_config().distractor.vit5_checkpoint, "available:", vit5_available())
gen = get_generator()                       # để lỗi nạp model nổi lên, không bị nuốt
for q in sample_questions_from_db(n):       # stem, answer, chunk.embed_text của câu v2 đã accepted
    raw = gen.generate(q.stem, q.answer, q.context, 8, "diverse_beam")
    kept = dedupe(raw, q.answer)
    cands = [Candidate(t, "vit5") for t in kept]
    filters.apply_rule_filters(cands, q.answer)
    entail, mode = filters.apply_nli_filter(cands, q.stem, q.answer, premise_for(q))
    print(q.stem, raw, [(c.text, c.rejected_at, c.copy_score, c.entail_prob) for c in cands])
```

2. Đọc kết quả để biết ứng viên mất ở bước nào: không sinh, rỗng, `form`, `copy` hay `nli`.
3. Sửa theo nguyên nhân:
   - Thiếu file: sửa đường dẫn hoặc mount, và ghi lại vào README.
   - Lỗi nạp: cố định phiên bản `transformers` trong `requirements/api.txt`; chạy CPU thì kiểm tra RAM của container Docker Desktop (cần ít nhất 6 GB).
   - Bị lọc hết ở `form`: xem `length_ratio: 0.4` có quá chặt với câu ngắn không. Có thể cho phép lệch theo số âm tiết tuyệt đối khi đáp án dưới 5 âm tiết.
   - Bị lọc hết ở `copy`: model học chép đáp án; giảm `copy_threshold` không phải cách sửa. Ghi nhận đây là hạn chế của checkpoint.
4. Sửa `from_vit5`: thay `log.warning` bằng việc ghi lỗi vào `calls` hoặc `report`, để lần sau lỗi hiện ra trong kết quả đánh giá.

**Nghiệm thu:** chạy 10 hạt giống, biết chính xác ứng viên ViT5 dừng ở đâu. Nếu ViT5 chạy được, có ứng viên `source=vit5` trong `distractor_candidates`.

### A2. Đo đóng góp của từng nguồn

1. Script `eval/v2/source_stats.py` đọc `distractor_candidates` (hoặc file `questions_*.jsonl`), xuất bảng theo nguồn:

| Nguồn | Số ứng viên | Bị loại `form` | `copy` | `nli` | Còn sống | Được chọn | Tỉ lệ được chọn |
| --- | --- | --- | --- | --- | --- | --- | --- |

2. Quy tắc quyết định:
   - ViT5 có tỉ lệ được chọn ≥ 10% và chất lượng ở G1 không kém LLM: giữ nguyên.
   - Dưới 10%: đặt `sources: [llm]`. Ghi vào báo cáo là kết quả âm, giải thích bằng lệch miền (huấn luyện trên Wikipedia và văn học, dùng trên slide kỹ thuật).

**Nghiệm thu:** có bảng theo nguồn và quyết định giữ hay tắt ViT5, kèm lý do.

### A3. Tăng số ứng viên

- `config.yaml`: `llm_candidates: 3 → 5`. Thêm tham số mới `min_alive: 5`: sau lọc còn ít hơn số này thì sinh bù ngay ở vòng đầu, thay vì chỉ sinh bù khi không chọn được bộ.
- `pipeline_v2.step_distractors`: thêm điều kiện `len(alive) < cfg.min_alive` để chạy vòng `refill`.

**Nghiệm thu:** trung vị số ứng viên còn sống ≥ 5. Câu có đúng 3 ứng viên (không có gì để chọn) dưới 20%.

### A4. Ghi đủ lý do trượt

- `run_ablation.generate`: khi bắt `StepFailed`, ghi `exc.feedback` vào `meta["reason"]`. Hiện chỉ có `failed=step`.
- Bảng `metrics.csv` thêm cột: `fail_key`, `fail_stem`, `fail_selection`, `fail_validator`.

**Nghiệm thu:** biết tỉ lệ trượt ở từng bước cho mỗi cấu hình.

### A5. Giảm chi phí

1. **Đo trước:** thêm `time.perf_counter()` quanh từng bước trong `pipeline_v2.generate` và lưu `report["timing"]`.
2. **Cách giảm, chọn theo kết quả đo:**
   - **Gộp key và stem** thành một lần gọi (prompt mới `mcq_key_stem.txt`, giữ kiểm tra evidence và kiểm tra lộ đáp án). Tiết kiệm 1 lần gọi.
   - **Chạy song song** bước giải thích của câu này với bước sinh câu tiếp theo; `bank.concurrency` đã có, chỉ cần kiểm tra giới hạn tốc độ của API.
   - **NLI và reranker theo lô:** gom ứng viên của nhiều câu nếu chạy CPU.
   - **Dùng model rẻ hơn cho bước giải thích:** thêm `models.mcq_explainer` vào config.
3. So lại chất lượng trước và sau khi gộp, bằng lớp A và E trên 30 hạt giống.

**Nghiệm thu:** ≤ 40 giây và ≤ 4 lần gọi LLM mỗi câu, chất lượng không giảm có ý nghĩa.

### A6. Chạy lớp S (solver) và J (judge)

`run_eval.py` hiện chỉ có lớp A và E. Prompt P1–P8 đã có trong `eval/quality/prompts/`.

1. Chọn model đánh giá **khác họ** với model sinh (README ghi đang chờ chọn `eval_models`). Nếu không có model khác họ, dùng `gpt-6-sol` và ghi rõ hạn chế.
2. Thêm `eval/quality/metrics/solver.py`:
   - **P8 (có ngữ cảnh):** tỉ lệ chọn đúng. Mục tiêu ≥ 95%; câu chọn sai thì đánh dấu là câu có thể sai hoặc mơ hồ.
   - **P7 (không ngữ cảnh):** càng thấp càng tốt.
   - **P6 (chỉ xem phương án):** gần 25% là tốt; cao thì đáp án đúng có dấu hiệu lộ.
   - Mỗi câu chạy 3 lần, xáo thứ tự phương án mỗi lần.
3. Thêm `eval/quality/metrics/judge.py` cho P1–P5 (bám nguồn, đúng duy nhất, câu hỏi tự đứng được, lỗi soạn câu, đúng mức Bloom).
4. `--layers` nhận thêm `S` và `J`. Báo cáo thêm hai bảng, kèm CI 95% bằng bootstrap (đã có `stats.py`).

**Nghiệm thu:** báo cáo có đủ 4 lớp A, E, S, J cho V1 và V2.

---

## Nhóm B: Đáp án nhiễu chẩn đoán

**Mục tiêu:** mọi đáp án nhiễu gắn với đúng một loại hiểu nhầm; bộ 3 đa dạng loại lỗi; loại lỗi tra được từ chữ cái A/B/C/D.

**Phụ thuộc:** A1–A3 (biết nguồn nào chạy, đủ ứng viên).

### B1. Một nguồn mô tả loại hiểu nhầm

Tạo `app/prompts/misconception_types.json`. File này dùng cho ba việc: prompt sinh, prompt gắn nhãn, và lời chẩn đoán hiển thị cho người học.

```json
{
  "nham_khai_niem_lan_can": {
    "ten": "Nhầm với khái niệm lân cận",
    "mo_ta_sinh": "nhầm với một khái niệm gần giống có trong ngữ cảnh",
    "chan_doan": "Bạn có thể đang nhầm khái niệm này với một khái niệm gần giống.",
    "vi_du": "Hỏi về TF-IDF nhưng mô tả của BM25"
  },
  "khai_quat_qua_muc": { "...": "..." },
  "dao_nhan_qua": { "...": "..." },
  "sai_thu_tu_buoc": { "...": "..." },
  "gan_nham_thuoc_tinh": { "...": "..." },
  "dung_nhung_khong_tra_loi": { "...": "..." },
  "sai_mot_chi_tiet": { "...": "..." }
}
```

- `mcq_misconception.txt`: thay danh sách cứng bằng biến `{error_types}`, sinh ra từ file này.
- Thêm `app/prompts/__init__.py: misconception_types()` (có `lru_cache`).

**Nghiệm thu:** sửa mô tả ở một chỗ thì prompt và giao diện đổi theo.

### B2. Gắn loại lỗi cho mọi ứng viên

Ứng viên ViT5 chưa có `error_type`. Ứng viên LLM có nhãn tự khai nhưng chưa được kiểm tra.

**Cách làm hai bước** (chỉ gắn cho ứng viên còn sống, trước bước chọn bộ):

1. **Lọc thô bằng embedding:** encode `stem + đáp án đúng + ứng viên` và encode mô tả của 7 loại lỗi bằng bge-m3 (đã nạp sẵn), lấy top 3 loại gần nhất. Bước này chỉ để thu hẹp lựa chọn, không quyết định.
2. **LLM chọn nhãn cho cả lô:** một lần gọi cho tất cả ứng viên của câu, prompt mới `mcq_tag_error.txt`:

```text
Câu hỏi: {stem}
Đáp án đúng: {answer}
Với mỗi phương án sai dưới đây, chọn MỘT loại hiểu nhầm mà nó thể hiện rõ nhất.
Nếu không thể hiện hiểu nhầm nào (chỉ là câu sai ngẫu nhiên), ghi "khong_ro".
{danh_sach_ung_vien_kem_top3_goi_y}
Trả về JSON: {"labels": [{"i": 0, "error_type": "...", "ly_do": "..."}]}
```

3. Ứng viên LLM đã tự khai nhãn: giữ nhãn tự khai nếu trùng với nhãn mới; khác thì lấy nhãn mới và lưu cả hai (`error_type_self`, `error_type`) để phân tích.
4. Ứng viên `khong_ro`: phạt điểm ở bước chọn bộ (B4), không loại hẳn.

**Code:** `candidates.py: async def tag_misconceptions(stem, answer, cands, calls) -> None`, gọi trong `step_distractors` sau `apply_nli_filter`. Bật tắt bằng `distractor.tag_errors`.

**Chi phí:** thêm 1 lần gọi LLM mỗi câu. Bù lại bằng việc gộp key và stem ở A5.

**Nghiệm thu:** 100% đáp án nhiễu được chọn có `error_type`; tỉ lệ `khong_ro` được báo cáo.

### B3. Khái niệm lân cận từ RAG

**Vấn đề:** E3 (đáp án nhiễu lạc đề) của V2 là 0,10, gấp đôi V1.

1. Trong `pipeline_v2.step_distractors`, truy xuất thêm 3 chunk liên quan tới `key_point` trong cùng môn học (không chỉ cùng tài liệu), bỏ các chunk đã có trong ngữ cảnh. Dùng `retrieve()` đã có.
2. Rút tiêu đề và câu đầu của các chunk đó thành danh sách "khái niệm lân cận".
3. Truyền vào `mcq_misconception.txt` qua biến `{neighbors}`, kèm hướng dẫn: loại `nham_khai_niem_lan_can` phải dùng một khái niệm trong danh sách này.
4. Tham số `distractor.neighbor_concepts: 3`.

**Nghiệm thu:** E3 ≤ 0,05 trên G1, các chỉ số khác không xấu đi.

### B4. Ràng buộc đa dạng loại lỗi khi chọn bộ

`selector.form_ok` đã có cơ chế nới dần (`both → length → convergence → none`). Thêm ràng buộc thứ ba:

```python
def diverse_ok(error_types: list[str | None], min_types: int) -> bool:
    known = [e for e in error_types if e and e != "khong_ro"]
    return len(set(known)) >= min(min_types, len(known)) and len(known) >= 2
```

- `select()` nhận thêm `error_types: list[str | None]`. Thứ tự nới: đủ cả 3 ràng buộc → bỏ hội tụ → bỏ độ dài → bỏ đa dạng → bỏ hết. Ghi `form_level` mới.
- Ứng viên `khong_ro` bị trừ điểm trước khi tính entropy: `s -= penalty_unclear` (mặc định 1.0).
- Tham số `distractor.min_error_types: 2`.
- **Test:** bổ sung `tests/test_v2_pipeline.py` với bộ ứng viên giả có loại lỗi trùng nhau, kiểm tra bộ chọn ra có 2 loại.

**Nghiệm thu:** ≥ 90% bộ có ≥ 2 loại lỗi; entropy trung bình không giảm quá 0,1.

### B5. Lưu ánh xạ phương án → ứng viên → loại lỗi

**Vấn đề:** `shuffle_options` xáo phương án nhưng không trả về thứ tự gốc, nên không biết chữ cái nào là ứng viên nào.

1. `common.ShuffledMCQ` thêm `origin: dict[str, int]`, là chỉ số gốc của từng chữ cái (0 = đáp án đúng, 1–3 = các ứng viên đã chọn theo thứ tự).
2. `pipeline_v2.generate` trả thêm trong `report` danh sách `picked_meta = [{"text", "source", "error_type"}]` theo đúng thứ tự trong `options`.
3. `bank_builder._save`:

```python
shuffled = shuffle_options(mcq)
option_meta = {}
for letter, idx in shuffled.origin.items():
    if idx == 0:
        option_meta[letter] = {"role": "key"}
    else:
        m = v2["picked"][idx - 1]
        option_meta[letter] = {"role": "distractor", "source": m["source"], "error_type": m["error_type"]}
q.option_meta = option_meta
# Sau db.flush() khi lưu distractor_candidates: điền candidate_id vào option_meta theo text khớp.
```

4. Migration `003_v3.sql`: `ALTER TABLE questions ADD COLUMN IF NOT EXISTS option_meta JSONB;`
5. `models.Question` thêm cột tương ứng.

**Nghiệm thu:** mọi câu v2/v3 mới có `option_meta` đủ 4 chữ cái, `error_type` khớp với `distractor_candidates.selected`.

### B6. Điền `option_meta` cho câu đã có

Script `scripts/backfill_option_meta.py`:

1. Với mỗi câu `pipeline_version='v2'` chưa có `option_meta`: lấy `distractor_candidates` có `selected=true`, so khớp text (chuẩn hoá `normalize_key`) với `options`.
2. Ứng viên chưa có `error_type` (ViT5): gọi `tag_misconceptions` của B2.
3. **Câu v1** (không có ứng viên): gọi `tag_misconceptions` trực tiếp trên 3 phương án sai, `source='v1'`.
4. Chạy thử ở chế độ `--dry-run`, in số câu khớp và không khớp.

**Nghiệm thu:** mọi câu `accepted` trong ngân hàng có `option_meta`.

### B7. Cấu hình C5 cho bảng so sánh

- `run_ablation.CONFIGS` thêm `"C5": {**C4, "distractor.tag_errors": True, "distractor.min_error_types": 2, "distractor.neighbor_concepts": 3}`.
- Xuất thêm `eval/quality/data/V3_items.jsonl` (qua `eval/quality/export.py`) để chạy lớp A, E, S, J.

**Nghiệm thu:** bảng so sánh có các cột C0, C1, C4, C5.

---

## Nhóm C: Dữ liệu người học

**Mục tiêu:** mỗi câu trả lời được ghi lại kèm người học, loại hiểu nhầm và thời gian.

**Phụ thuộc:** B5 (cần `option_meta`). C1 có thể làm song song với B.

### C1. Người dùng tối thiểu

Không làm đăng ký và mật khẩu. Người học nhập tên và mã (ví dụ mã sinh viên) ở thanh bên.

- Migration `003_v3.sql`:

```sql
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id);
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'normal';
```

- API `POST /users/login {code, display_name}`: trả `user_id`, tạo mới nếu chưa có. File mới `app/api/users.py`.
- UI `ui/views/left.py`: ô nhập mã; lưu `user_id` vào `st.session_state` (`ui/views/state.py`).
- `AttemptIn` thêm `user_id: int | None`. Giữ `user_name` để tương thích ngược.

### C2. Bảng `responses`

```sql
CREATE TABLE IF NOT EXISTS responses (
  id BIGSERIAL PRIMARY KEY,
  attempt_id INT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  user_id INT REFERENCES users(id),
  question_id BIGINT NOT NULL REFERENCES questions(id),
  chosen CHAR(1),
  is_correct BOOLEAN NOT NULL,
  candidate_id BIGINT REFERENCES distractor_candidates(id),
  error_type TEXT,
  concept TEXT,
  time_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS responses_user_idx ON responses (user_id, created_at);
CREATE INDEX IF NOT EXISTS responses_question_idx ON responses (question_id);
```

`concept` lấy từ `validation.key_point` của câu hỏi, chép sang để truy vấn hồ sơ nhanh.

### C3. Ghi `responses` khi nộp bài

Trong `attempts.submit_attempt`, sau khi tạo `attempt`:

```python
for q in questions:
    chosen = body.answers[q.id]
    meta = (q.option_meta or {}).get(chosen, {})
    db.add(Response(
        attempt_id=attempt.id, user_id=body.user_id, question_id=q.id, chosen=chosen,
        is_correct=chosen == q.answer,
        candidate_id=meta.get("candidate_id"),
        error_type=meta.get("error_type") if chosen != q.answer else None,
        concept=(q.validation or {}).get("key_point"),
        time_ms=(body.times_ms or {}).get(q.id),
    ))
```

Sau khi ghi, gọi cập nhật hồ sơ (D3) và Elo (D7), cùng transaction hoặc bằng `BackgroundTasks`.

**Kiểm thử:** test API nộp một đề 3 câu (1 đúng, 2 sai) → có 3 dòng `responses`, 2 dòng có `error_type`.

### C4. Thời gian làm từng câu (tuỳ chọn)

Streamlit không có sự kiện theo câu một cách tự nhiên. Cách đơn giản: nếu UI hiện từng câu một thì ghi `time.time()` khi chuyển câu. Nếu hiện cả đề trên một trang thì bỏ qua, để `time_ms = NULL`.

**Nghiệm thu nhóm C:** nộp bài từ UI sinh đủ dòng `responses`, truy vấn được "người học X đã chọn những loại lỗi nào".

---

## Nhóm D: Chẩn đoán và cá nhân hoá

**Mục tiêu:** người học thấy mình nhầm gì, chọn được mức độ khó, và có đề luyện nhắm vào điểm yếu.

**Phụ thuộc:** C. D4–D5 chỉ cần B5 và dữ liệu sẵn có, làm được trước C.

### D1. Chẩn đoán ở màn hình xem lại

- `schemas.ReviewItem` thêm `misconception: dict | None` (`ten`, `chan_doan` lấy từ B1).
- `attempts.review_attempt`: nếu chọn sai, tra `option_meta[chosen].error_type` → mô tả.
- `ui/views/quiz.py`: hiện ô thông báo dưới phương án đã chọn: "🔍 Bạn có thể đang nhầm: *[chan_doan]*", ngay trên lời giải thích của phương án đó (đã có `rationales`).

### D2. Chatbot biết hiểu nhầm

- Khi mở hội thoại từ một câu sai (đã có `conversations.question_id`), `chat/answerer.py` đưa thêm vào system prompt: câu hỏi, phương án đã chọn, loại hiểu nhầm, đáp án đúng, câu evidence.
- `chat_system.txt` thêm hướng dẫn: giải thích vì sao phương án đó sai theo đúng hiểu nhầm, rồi dẫn về slide nguồn. Không đưa thẳng đáp án nếu người học chỉ hỏi gợi ý.
- `conversations` thêm `attempt_id` (đã có) để biết lựa chọn của người học.

### D3. Hồ sơ hiểu nhầm

```sql
CREATE TABLE IF NOT EXISTS misconception_stats (
  user_id INT REFERENCES users(id),
  concept TEXT,
  error_type TEXT,
  score REAL NOT NULL DEFAULT 0,      -- có suy giảm theo thời gian
  n_seen INT NOT NULL DEFAULT 0,
  last_seen TIMESTAMPTZ,
  PRIMARY KEY (user_id, concept, error_type)
);
```

`app/learner/profile.py`:

- **Cập nhật sau mỗi lần nộp:** chọn đáp án nhiễu loại `e` của khái niệm `c` thì `score = score * decay + 1`. Trả lời đúng một câu có đáp án nhiễu loại `e` thì `score = score * decay - 0.5` (không âm). `decay = 0.5 ** (days_since_last / weakness_decay_days)`.
- **`top_weaknesses(user_id, k)`:** trả về top k cặp (khái niệm, loại lỗi) theo `score`.
- **API** `GET /users/{id}/profile`: điểm yếu, số câu đã làm, tỉ lệ đúng theo chương.

### D4. Ước lượng độ khó ban đầu

Câu v2 đã lưu `selection.margin` (xác suất của đáp án đúng trừ xác suất của đáp án nhiễu mạnh nhất, theo reranker). Margin nhỏ nghĩa là đáp án nhiễu cạnh tranh mạnh, tức câu khó hơn.

```python
def estimate(q) -> str:
    margin = (q.selection or {}).get("margin")
    if margin is None:                     # câu v1: dùng cos trung bình đáp án nhiễu – key (tính 1 lần khi backfill)
        margin = 1 - mean_cos_distractor_key(q)
    bloom_bonus = {"remember": 0.15, "understand": 0.0, "apply": -0.15}[q.bloom_level]
    x = margin + bloom_bonus
    return "easy" if x >= 0.5 else "medium" if x >= 0.25 else "hard"
```

- Ngưỡng đặt trong `config.yaml: learner.difficulty_levels` và **hiệu chỉnh theo phân vị** để ba mức có số câu gần bằng nhau trong ngân hàng.
- Cột `questions.difficulty_est`; script `scripts/backfill_difficulty.py` tính cho câu đã có. Tính luôn khi lưu câu mới (`_save`).

### D5. Tạo đề theo mức độ khó

- `QuizIn` thêm `difficulty: Literal["easy","medium","hard","mixed"] = "mixed"`.
- `quiz_sampler._candidates`: lọc theo `difficulty_est` nếu khác `mixed`. Không đủ câu thì bù từ mức gần nhất (hard → medium → easy) và trả cảnh báo cho UI.
- `ui/views/center.py`: thêm ô chọn mức độ cạnh tỉ lệ Bloom.

### D6. Chế độ "Luyện điểm yếu"

`quiz_sampler.create_weakness_quiz(user_id, n)`:

1. Lấy `top_weaknesses(user_id, k=5)`.
2. Chấm điểm mỗi câu ứng viên trong phạm vi:
   `ưu tiên = 2·[khái niệm thuộc điểm yếu] + 1·[có đáp án nhiễu cùng loại lỗi điểm yếu] − 0.5·[đã làm đúng gần đây] − 1·[đã làm trong 24 giờ qua]`
3. Lấy top n theo điểm, xáo thứ tự, giữ vòng xoay theo slide để không dồn vào một slide.
4. Người học chưa có dữ liệu: trả về đề thường, kèm thông báo "làm thêm vài đề để hệ thống biết điểm yếu".
5. Mỗi câu lưu `reason` (vì sao được chọn) vào `quiz_questions` để hiển thị và phân tích.

UI: nút "Luyện điểm yếu" ở thanh bên khi đã đăng nhập.

### D7. Elo (chế độ Tự động)

`app/learner/elo.py`:

```python
def expected(user_elo, item_elo):
    return 1 / (1 + 10 ** ((item_elo - user_elo) / 400))

def update(user_elo, item_elo, correct, k_user=24, k_item=8):
    p = expected(user_elo, item_elo)
    return user_elo + k_user * (correct - p), item_elo - k_item * (correct - p)
```

- `user_skill(user_id, concept, elo)` và `questions.difficulty_elo`. Khởi tạo Elo của câu từ `difficulty_est` (easy 1100, medium 1200, hard 1300).
- K của câu nhỏ hơn K của người, vì mỗi câu có nhiều người làm.
- Chế độ "Tự động": chọn câu có `expected` trong khoảng `[0.7, 0.8]` với Elo của người học.

### D8. Bản đồ thành thạo

- Trang mới hoặc mục trong `ui/views/left.py`: bảng nhiệt theo chương × khái niệm, màu theo mức thành thạo (Elo hoặc tỉ lệ đúng có làm trơn).
- Danh sách "3 hiểu nhầm bạn hay mắc" kèm nút luyện ngay.

**Nghiệm thu nhóm D:** người học thấy chẩn đoán khi sai; chọn được ba mức độ; đề luyện điểm yếu chứa câu liên quan tới điểm yếu (kiểm bằng `reason`).

---

## Nhóm E: Phân tích câu hỏi và tự cải thiện ngân hàng

**Mục tiêu:** ngân hàng tốt dần lên nhờ dữ liệu làm bài.

**Phụ thuộc:** C, và có dữ liệu từ G4.

### E1. Thống kê từng câu

`app/learner/item_analysis.py`, chạy theo lệnh hoặc theo lịch:

- **Độ khó p:** tỉ lệ trả lời đúng.
- **Độ phân biệt D:** tỉ lệ đúng của nhóm 27% điểm cao nhất trừ nhóm 27% thấp nhất (tính theo điểm của cả bài làm). Cách khác là tương quan point-biserial.
- **Tỉ lệ chọn từng đáp án nhiễu,** tách theo nhóm trên và nhóm dưới.
- Chỉ tính khi câu có ít nhất `min_responses_for_analysis` lượt (mặc định 20).
- API `GET /analytics/questions?document_id=` cho giảng viên.

### E2. Đánh dấu đáp án nhiễu kém

| Dấu hiệu | Quy tắc | Ý nghĩa |
| --- | --- | --- |
| Không ai chọn | tỉ lệ chọn < 5% | Đáp án nhiễu vô dụng |
| Nhóm giỏi chọn nhiều | nhóm trên chọn nhiều hơn nhóm dưới | Có thể đúng một phần, hoặc câu hỏi mơ hồ |
| Hút hơn đáp án đúng | tỉ lệ chọn > tỉ lệ đúng | Kiểm tra lại câu hỏi |
| Câu không phân biệt | D < 0,1 | Câu quá dễ, quá khó hoặc lỗi |

Lưu vào bảng `item_flags(question_id, letter, flag, created_at, resolved)`.

### E3. Sinh lại đáp án nhiễu

`pipeline_v2.regenerate_distractor(question, letter)`:

1. Nạp lại ngữ cảnh của câu, cùng key và stem (đã lưu trong `validation`).
2. Gọi `_collect` với `avoid` gồm 3 phương án hiện tại và các ứng viên đã bị đánh dấu trước đó. Yêu cầu loại lỗi chưa có trong bộ.
3. Chạy lại các bộ lọc, chấm điểm, chọn 1 ứng viên thay thế giữ ràng buộc của bộ.
4. Lưu phiên bản cũ: `questions.history JSONB` (danh sách `{options, option_meta, replaced_at, reason}`). Câu đã sửa thì đặt lại thống kê từ thời điểm sửa.
5. Câu có cờ "hút hơn đáp án đúng" thì **không** tự sửa, chỉ đưa vào danh sách để giảng viên xem.

### E4. Hiệu chỉnh độ khó từ dữ liệu

- Khi đủ dữ liệu, cập nhật `difficulty_est` theo phân vị của p thực tế.
- Khi đủ lớn (vài trăm lượt), thử IRT 1PL/2PL bằng thư viện `girth` và so với Elo. Phần này là tuỳ chọn.
- Báo cáo: tương quan giữa độ khó ước lượng ban đầu (D4) và p thực tế. Đây là bằng chứng cho cách ước lượng.

### E5. Thống kê cho giảng viên

- Trang "Hiểu nhầm phổ biến": nhóm `responses` theo (khái niệm, loại lỗi). Hiện kiểu "34% lượt sai ở khái niệm *TF-IDF* thuộc loại *nhầm khái niệm lân cận*", kèm ví dụ phương án bị chọn nhiều nhất.

**Nghiệm thu nhóm E:** có bảng thống kê câu hỏi; đáp án nhiễu bị đánh dấu được sinh lại và lưu lịch sử.

---

## Nhóm F: Dạng câu hỏi mới

**Mục tiêu:** thêm dạng câu kiểm tra hiểu bài thật, dùng lại đáp án nhiễu và loại lỗi đã có.

**Phụ thuộc:** B (đáp án nhiễu có loại lỗi). Phần chấm điểm và hồ sơ cần C và D.

### F1. Schema chung

Migration `004_qtypes.sql`:

```sql
ALTER TABLE questions ADD COLUMN IF NOT EXISTS qtype TEXT NOT NULL DEFAULT 'mcq';
ALTER TABLE questions ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE questions ALTER COLUMN answer DROP NOT NULL;
ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_answer_check;
ALTER TABLE questions ADD CONSTRAINT questions_answer_check
  CHECK ((qtype = 'mcq' AND answer IN ('A','B','C','D')) OR qtype <> 'mcq');
ALTER TABLE responses ADD COLUMN IF NOT EXISTS answer_payload JSONB, ADD COLUMN IF NOT EXISTS score REAL;
```

`payload` theo từng dạng (Pydantic, discriminated union theo `qtype` trong `schemas.py`):

| qtype | payload | Đáp án người học | Chấm điểm |
| --- | --- | --- | --- |
| `order` | `{"items": [...], "correct_order": [2,0,1,3]}` | thứ tự | Kendall tau chuẩn hoá về [0, 1] hoặc tỉ lệ cặp đúng |
| `gap_match` | `{"text": "... {{1}} ... {{2}}", "answers": {"1": "...", "2": "..."}, "bank": [...]}` | `{"1": "...", "2": "..."}` | tỉ lệ ô đúng |
| `match` | `{"left": [...], "right": [...], "pairs": {"0": 2, "1": 0}}` | các cặp | tỉ lệ cặp đúng |
| `hottext` | `{"tokens": [...], "error_spans": [[5,9]], "corrections": [...]}` | các vị trí được đánh dấu | F1 giữa vị trí chọn và vị trí lỗi |

`attempts.submit_attempt` chấm theo `qtype`; điểm bài là tổng điểm từng phần.

### F2. Sắp xếp thứ tự

- Hạt giống: chunk có `answer_type = buoc_quy_trinh`, hoặc chunk có danh sách đánh số hay nhiều gạch đầu dòng nối tiếp.
- Prompt `q_order.txt`: trích 4–6 bước nguyên văn kèm evidence. Kiểm tra mỗi bước khớp slide (dùng lại `evidence_coverage`).
- Lỗi chẩn đoán: cặp bước bị đảo → `sai_thu_tu_buoc` gắn với cặp đó.

### F3. Kéo thả điền khuyết

- Lấy câu evidence của một câu `mcq` đã duyệt, hoặc câu định nghĩa trong slide; bỏ trống 2–4 thuật ngữ chính (LLM chọn).
- Ngân hàng từ = các đáp án + 2–3 từ thừa lấy từ ứng viên trong `distractor_candidates` đã qua lọc NLI. Đây là chỗ dùng lại kết quả của pipeline v2.
- Kiểm tra: mỗi chỗ trống chỉ có một từ hợp lệ trong ngân hàng (NLI: thay từ thừa vào không được entail).

### F4. Nối

- Lấy 4–5 cặp (thuật ngữ, định nghĩa hoặc ví dụ) trong cùng chương từ các câu `mcq` có `answer_type ∈ {thuat_ngu, dinh_nghia}`.
- Thêm 1–2 vế phải thừa từ khái niệm lân cận (B3).
- Kiểm tra: không có vế phải nào hợp với hai vế trái (dùng cos bge-m3 và NLI).

### F5. Tìm lỗi sai

- Lấy câu evidence, thay 1–2 cụm bằng đáp án nhiễu có loại `sai_mot_chi_tiet` hoặc `gan_nham_thuoc_tinh` (đã có sẵn từ B).
- Người học đánh dấu cụm sai; phần giải thích hiện bản đúng và loại lỗi.
- Gắn với kỹ thuật "ví dụ có lỗi". Có thể tham khảo skill `erroneous-example-designer` khi viết prompt.

### F6. Giao diện

- Kiểm tra component `streamlit-sortables` cho `order` và `gap_match`. Nếu không ổn định thì dùng phương án thay thế: `st.selectbox` cho từng vị trí hoặc từng chỗ trống.
- `match`: mỗi vế trái một `st.selectbox` chọn vế phải.
- `hottext`: hiển thị các cụm thành nút bật tắt (`st.toggle` hoặc `st.pills` nếu phiên bản Streamlit có).
- Màn hình xem lại cho từng dạng: hiện đáp án đúng, phần làm đúng và sai, và lời giải thích.

### F7. Hồ sơ cho dạng mới

| Dạng | Sự kiện sai | Loại lỗi ghi vào hồ sơ |
| --- | --- | --- |
| `order` | đảo cặp bước | `sai_thu_tu_buoc` |
| `gap_match` | chọn từ thừa | `error_type` của từ thừa đó |
| `match` | nối nhầm sang vế thừa hoặc vế khác | `nham_khai_niem_lan_can` |
| `hottext` | bỏ sót lỗi | `error_type` của cụm đã cài |

**Nghiệm thu nhóm F:** sinh, làm bài, chấm điểm và xem lại được cho ít nhất 2 dạng mới; câu sai của dạng mới được ghi vào hồ sơ.

---

## Nhóm G: Đánh giá và báo cáo

**Mục tiêu:** chứng minh v3 tốt hơn bằng số liệu có khoảng tin cậy. Tài liệu khớp với code.

### G1. So sánh tự động V1, V2, V3

1. Cố định tập hạt giống: dùng lại 60 hạt giống của 08/11 (chương 4 và 9, id 17 và 22, không dùng khi huấn luyện ViT5), thêm 40 hạt giống từ môn thị giác máy tính để kiểm tra khả năng tổng quát.
2. Sinh: `python -m eval.v2.run_ablation --docs 17 22 ... --n-seeds 100 --configs C0 C4 C5`.
3. Xuất và chạy: `python -m eval.quality.run_eval --layers A E S J --versions V1 V2 V3`.
4. Bảng chính trong báo cáo: các chỉ tiêu ở mục 1.2 của `ke-hoach-v3.md`, kèm CI 95% và đánh dấu hiệu có ý nghĩa.

### G2. Người chấm

1. Lấy 40 câu V1 và 40 câu V3 cùng hạt giống; trộn và ẩn phiên bản (`eval/mcq/step3_sample.py`).
2. Hai người chấm độc lập theo `eval/mcq/huong_dan_cham.md`, thêm tiêu chí cho từng đáp án nhiễu: chắc chắn sai (có/không), hợp lý (1–5), thể hiện hiểu nhầm rõ (có/không).
3. Tính đồng thuận (`step4_agreement.py`) và so sánh V1 với V3 bằng kiểm định cặp (cùng hạt giống).

### G3. Kiểm tra nhãn hiểu nhầm

1. Lấy 60 đáp án nhiễu, ngẫu nhiên phân tầng theo loại lỗi.
2. Hai người gán nhãn độc lập theo `misconception_types.json`, không thấy nhãn của LLM.
3. Tính Cohen's kappa người–người và người–LLM; lập ma trận nhầm lẫn giữa các loại.
4. Nếu kappa người–người thấp (< 0,4) thì taxonomy quá mơ hồ: gộp các loại hay bị nhầm với nhau, rồi chạy lại.

### G4. Thử nghiệm với sinh viên

1. **Chuẩn bị:** 2 đề × 15 câu, cùng phạm vi (ví dụ chương 4 và 9), trộn câu V1 và V3. Mỗi sinh viên đăng nhập bằng mã riêng.
2. **Thực hiện:** 10–20 sinh viên làm đề 1; xem chẩn đoán; làm đề luyện điểm yếu; làm đề 2.
3. **Phiếu khảo sát ngắn:** chẩn đoán có đúng với suy nghĩ của bạn không (1–5); lời giải thích có giúp hiểu không (1–5).
4. **Phân tích:** E1 cho từng câu; so sánh độ phân biệt D giữa câu V1 và V3; tỉ lệ đáp án nhiễu không ai chọn; tỉ lệ đúng theo `difficulty_est` (phải giảm dần từ dễ đến khó).

### G5. Kiểm tra vòng cá nhân hoá

- So sánh tỉ lệ mắc lại cùng loại lỗi trên cùng khái niệm ở đề 2, giữa người đã làm đề luyện điểm yếu và người không làm (nếu đủ người thì chia ngẫu nhiên hai nhóm).
- Mẫu nhỏ nên chỉ báo cáo mô tả kèm CI, không khẳng định nhân quả.

### G6. Tài liệu

| Tài liệu | Cập nhật |
| --- | --- |
| `README.md` | Tính năng v3, cách bật, migration 003/004 |
| `docs/tong-quan-he-thong.md` | Bước gắn loại lỗi, `option_meta`, hồ sơ người học, các dạng câu |
| `docs/so-do-he-thong.html` | Luồng vòng lặp mới |
| Báo cáo | Chương phương pháp (câu nhiễu chẩn đoán, ràng buộc đa dạng, cá nhân hoá) và chương thực nghiệm (G1–G5), cùng kết quả âm của ViT5 nếu có |

---

## Danh sách file sẽ thêm hoặc sửa

| Loại | File |
| --- | --- |
| Thêm | `migrations/003_v3.sql`, `migrations/004_qtypes.sql` |
| Thêm | `app/prompts/misconception_types.json`, `mcq_tag_error.txt`, `mcq_key_stem.txt`, `q_order.txt`, `q_gap.txt`, `q_match.txt`, `q_hottext.txt` |
| Thêm | `app/learner/` gồm `profile.py`, `difficulty.py`, `elo.py`, `item_analysis.py` |
| Thêm | `app/api/users.py`, `app/api/analytics.py` |
| Thêm | `eval/v2/diagnose_vit5.py`, `eval/v2/source_stats.py`, `eval/quality/metrics/solver.py`, `eval/quality/metrics/judge.py` |
| Thêm | `scripts/backfill_option_meta.py`, `scripts/backfill_difficulty.py` |
| Sửa | `app/generation/pipeline_v2.py`, `candidates.py`, `selector.py`, `common.py`, `bank_builder.py`, `quiz_sampler.py` |
| Sửa | `app/api/attempts.py`, `app/api/quizzes.py`, `app/chat/answerer.py`, `app/models.py`, `app/schemas.py`, `app/config.py`, `app/prompts/mcq_misconception.txt`, `chat_system.txt` |
| Sửa | `ui/views/left.py`, `center.py`, `quiz.py`, `state.py`, `ui/api_client.py` |
| Sửa | `config.yaml`, `eval/v2/run_ablation.py`, `eval/quality/run_eval.py`, `tests/test_v2_pipeline.py` |
