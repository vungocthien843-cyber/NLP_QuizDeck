# Kế hoạch phiên bản 3: câu nhiễu chẩn đoán và cá nhân hoá

Cập nhật: 14/11/2026

> v1 sinh câu hỏi một chiều. v2 sinh và chọn đáp án nhiễu tốt hơn. v3 biến đáp án nhiễu thành **công cụ chẩn đoán**: mỗi đáp án nhiễu gắn với một hiểu nhầm cụ thể. Lựa chọn sai của người học quay lại quyết định đề tiếp theo, lời giải thích và nội dung chatbot.

## 1. Mục tiêu hệ thống sau cải thiện

### 1.1 Mục tiêu tổng quát

1. **Đáp án nhiễu có chẩn đoán.** Mọi đáp án nhiễu trong ngân hàng gắn với một loại hiểu nhầm. Người học chọn sai thì hệ thống biết họ đang nhầm điều gì.
2. **Chất lượng đáp án nhiễu được chứng minh bằng số liệu.** v3 phải hơn v1 có ý nghĩa thống kê ở các chỉ số về đáp án nhiễu, không chỉ ở các chỉ số do luật lọc tạo ra.
3. **Vòng lặp người học.** Hệ thống chuyển từ luồng một chiều (sinh → làm bài → hết) sang vòng lặp: làm bài → ghi hiểu nhầm → chẩn đoán → đề luyện tập nhắm vào điểm yếu.
4. **Người dùng tự chọn mức độ khó.** Có ba mức Dễ / Trung bình / Khó, cộng chế độ Tự động và chế độ Luyện điểm yếu.
5. **Nhiều dạng câu hỏi hơn.** Thêm các dạng kiểm tra hiểu bài thật: sắp xếp thứ tự, kéo thả điền khuyết, nối, tìm lỗi sai.
6. **Chi phí sinh câu hỏi chấp nhận được** khi chạy nền.

### 1.2 Chỉ tiêu đo được

Giá trị "hiện tại" lấy từ `eval/quality/results/20261108-115733` và `eval/v2/results/20261106-020325`. Chỉ tiêu là đề xuất, sẽ chỉnh lại sau khi đo lại ở hạng mục A.

| Nhóm | Chỉ số | Hiện tại | Chỉ tiêu v3 |
| --- | --- | --- | --- |
| Đáp án nhiễu | Người chấm: "phương án sai hợp lý" (thang 1–5) | ≈ 3,0 (v1) | ≥ 3,5 |
| Đáp án nhiễu | Tỉ lệ đáp án nhiễu trong dải a ≤ cos(d, key) ≤ b (E2) | V1 0,785 · V2 0,673 | ≥ 0,80 |
| Đáp án nhiễu | Tỉ lệ đáp án nhiễu lạc đề (E3) | V1 0,051 · V2 0,100 | ≤ 0,05 |
| Đáp án nhiễu | Bộ có độ dài lệch > 1,5 lần (D3) | V1 0,119 · V2 0,240 | ≤ 0,10 |
| Đáp án nhiễu | Có cặp đáp án nhiễu cos > 0,9 (D6) | V1 0,153 · V2 0,200 | ≤ 0,10 |
| Câu hỏi | Solver có ngữ cảnh chọn đúng | chưa đo | ≥ 95% |
| Câu hỏi | Solver không ngữ cảnh chọn đúng | chưa đo | thấp hơn v1 |
| Câu hỏi | Solver chỉ xem phương án chọn đúng | chưa đo | ≈ 25–35% |
| Chẩn đoán | Đáp án nhiễu có `error_type` | chỉ ứng viên LLM | 100% |
| Chẩn đoán | Bộ 3 có ≥ 2 loại lỗi khác nhau | chưa đo | ≥ 90% |
| Chẩn đoán | Đồng thuận nhãn hiểu nhầm giữa người và LLM (kappa) | chưa đo | ≥ 0,6 |
| Pipeline | Ứng viên còn lại sau lọc | 17/28 câu chỉ còn đúng 3 | trung vị ≥ 5 |
| Pipeline | Tỉ lệ hạt giống sinh được câu | 0,83 (08/11), 0,45 (06/11) | ≥ 0,85 |
| Pipeline | Thời gian / số lần gọi LLM cho mỗi câu | 95 s · 4,75 lần | ≤ 40 s · ≤ 4 lần |
| Người học | Tỉ lệ đúng theo mức độ khó | chưa có | giảm dần Dễ > TB > Khó |
| Người học | Đáp án nhiễu không ai chọn (sau ≥ 20 lượt) | chưa có | ≤ 10% sau khi sinh lại |

## 2. Hiện trạng và vấn đề

**Đã có:**

- Pipeline v2 8 bước, gồm ViT5, LLM sinh theo 7 loại hiểu nhầm, lọc luật, lọc NLI, chọn bộ 3 bằng entropy có δ.
- Bảng `distractor_candidates` lưu mọi ứng viên.
- Bộ đánh giá 3 tầng.
- Ngân hàng câu hỏi được sinh trước, nên tạo đề không gọi LLM.
- Chatbot RAG gắn được với từng câu hỏi.

**Vấn đề phát hiện khi đọc code và kết quả:**

| # | Vấn đề | Bằng chứng | Hệ quả |
| --- | --- | --- | --- |
| V1 | ViT5 không đóng góp ứng viên | Lần chạy 06/11: 183/183 ứng viên của C4 đến từ LLM; C2 (chỉ ViT5) đạt 0/60 câu | "C4" lần đó thực chất chỉ là C1 |
| V2 | Bước chọn bộ 3 thường không có gì để chọn | 17/28 câu C4 chỉ còn đúng 3 ứng viên sau lọc | Đóng góp K4 (entropy + δ) chưa thể hiện |
| V3 | v2 chưa thắng v1 rõ ràng | Chỉ D5 và C2 cải thiện có ý nghĩa; E2, E3, D3 xấu đi | Chưa chứng minh được giá trị của v2 |
| V4 | Thiếu lớp đánh giá | Chưa chạy solver (S), judge (J), người chấm cho v2 | Chưa kết luận được về độ khó và tính đúng duy nhất |
| V5 | Không biết người học chọn sai vì sao | `attempts.answers` chỉ lưu chữ cái; phương án đã bị xáo khi lưu | Không làm được chẩn đoán và cá nhân hoá |
| V6 | Không có định danh người học | Chỉ có `user_name` dạng chữ tự do | Không có hồ sơ người học |
| V7 | Độ khó chỉ điều chỉnh qua tỉ lệ Bloom | `quiz_sampler.py` | Người dùng không chọn được mức độ khó |
| V8 | Chỉ có dạng 4 chọn 1 | Schema `questions` cố định A–D | Chưa kiểm tra được hiểu quy trình, phân biệt khái niệm |
| V9 | Chi phí cao | 95 s và 4,75 lần gọi LLM mỗi câu, so với 4 s của v1 | Sinh ngân hàng chậm |

## 3. Luồng hệ thống v3

```text
HIỆN TẠI (v2)
Slide → key → stem → ứng viên → lọc → chọn 3 → giải thích → ngân hàng
      → tạo đề (phạm vi, Bloom) → làm bài → chấm điểm → xem lại (+ chatbot)

v3
Slide → key → stem → ứng viên (+ khái niệm lân cận từ RAG) → lọc
      → GẮN LOẠI HIỂU NHẦM → chọn 3 (entropy + δ + đa dạng lỗi) → giải thích → ngân hàng (+ option_meta)
      → tạo đề (phạm vi, Bloom, MỨC ĐỘ KHÓ, ĐIỂM YẾU, DẠNG CÂU)
      → làm bài → chấm điểm → GHI TỪNG CÂU TRẢ LỜI + HIỂU NHẦM
      → xem lại + CHẨN ĐOÁN + chatbot giải thích đúng hiểu nhầm
      → HỒ SƠ NGƯỜI HỌC ──→ quay lại tạo đề
      → PHÂN TÍCH CÂU HỎI ──→ sinh lại đáp án nhiễu không ai chọn
```

| Thành phần | v2 hiện tại | v3 |
| --- | --- | --- |
| Nguồn ứng viên | ViT5 + LLM (thực tế chỉ LLM, 3 ứng viên) | Đã xác minh ViT5 (sửa hoặc tắt), LLM 5–6 ứng viên, có khái niệm lân cận |
| Loại hiểu nhầm | Chỉ ứng viên LLM, nằm ở bảng phụ | Mọi đáp án nhiễu, gắn với A/B/C/D |
| Chọn bộ 3 | Entropy + δ + ràng buộc hình thức | Thêm ràng buộc đa dạng loại lỗi, có đủ ứng viên để chọn |
| Bài làm | Chữ cái đã chọn | Từng câu trả lời, loại hiểu nhầm, thời gian |
| Người học | Không có | Bảng người dùng, hồ sơ hiểu nhầm, mức thành thạo |
| Tạo đề | Phạm vi, số câu, Bloom | Thêm mức độ khó, luyện điểm yếu, chọn dạng câu |
| Xem lại | Giải thích, trích slide, chatbot | Thêm chẩn đoán hiểu nhầm, chatbot biết hiểu nhầm |
| Ngân hàng | Sinh một lần | Tự sinh lại đáp án nhiễu kém dựa trên dữ liệu làm bài |
| Dạng câu | 4 chọn 1 | Thêm sắp xếp, kéo thả điền khuyết, nối, tìm lỗi sai |

## 4. Công việc phải làm

Mức ưu tiên: **P0** là bắt buộc để v3 có nghĩa, **P1** hoàn thiện cá nhân hoá, **P2** mở rộng.

### A. Đo lại và sửa lỗi nền (P0)

| # | Việc | File | Xong khi |
| --- | --- | --- | --- |
| A1 | Tìm vì sao ViT5 không sinh ứng viên: checkpoint, lỗi khi nạp, log cảnh báo trong `from_vit5` | `app/local_models/__init__.py`, `app/generation/candidates.py` | Chạy 10 hạt giống, có ứng viên `source=vit5` trong `distractor_candidates` |
| A2 | Đo đóng góp ViT5: tỉ lệ ứng viên được chọn theo nguồn, tỉ lệ bị loại ở từng bước. Dưới khoảng 10% thì tắt (`sources: [llm]`) và báo cáo kết quả âm | script mới `eval/v2/source_stats.py` | Có bảng theo nguồn |
| A3 | Tăng `llm_candidates` lên 5–6 để bước chọn bộ có lựa chọn | `config.yaml` | Trung vị số ứng viên còn lại ≥ 5 |
| A4 | Ghi lý do trượt vào kết quả ablation (hiện `reason` toàn `None`) | `eval/v2/run_ablation.py` | Thống kê được trượt ở bước nào |
| A5 | Đo thời gian từng bước; giảm chi phí (gộp bước key + stem, hoặc chạy giải thích bằng model rẻ hơn) | `pipeline_v2.py`, `llm_client.py` | ≤ 40 s và ≤ 4 lần gọi LLM mỗi câu |
| A6 | Chạy lớp S (solver P6–P8) và J (judge P1–P5) cho V1 và V2 | `eval/quality/run_eval.py` | Bảng S, J kèm CI 95% |

### B. Đáp án nhiễu chẩn đoán (P0)

| # | Việc | File | Xong khi |
| --- | --- | --- | --- |
| B1 | Viết mô tả và ví dụ cho từng loại trong 7 loại hiểu nhầm (dùng chung cho sinh, gắn nhãn, hiển thị) | mới `app/prompts/misconception_types.json` | Một nguồn duy nhất, prompt `mcq_misconception` đọc từ đây |
| B2 | Gắn `error_type` cho mọi ứng viên còn sống, gồm ViT5: embedding so với mô tả loại lỗi để lấy top 3, rồi một lần gọi LLM chọn cho cả lô | `candidates.py`: `tag_misconceptions()`; prompt mới `mcq_tag_error.txt` | 100% đáp án nhiễu được chọn có `error_type` |
| B3 | Đưa 2–3 khái niệm lân cận (truy xuất hybrid, bỏ chunk hạt giống) vào prompt hiểu nhầm | `mcq_misconception.txt`, `pipeline_v2.py`, `retrieval/hybrid.py` | E3 (lạc đề) ≤ 0,05 |
| B4 | Ràng buộc đa dạng: bộ 3 có ≥ 2 loại lỗi; nới dần như ràng buộc hình thức hiện có | `selector.py` (`form_ok`, `form_level`) | ≥ 90% bộ có ≥ 2 loại lỗi |
| B5 | Lưu ánh xạ phương án → ứng viên → loại lỗi sau khi xáo | migration `003`: `questions.option_meta JSONB`; `bank_builder.py` | Mỗi câu v2/v3 có `{"B": {"candidate_id", "error_type", "source"}}` |
| B6 | Script điền `option_meta` cho câu đã có (so khớp text với `distractor_candidates`) | mới `scripts/backfill_option_meta.py` | Câu cũ dùng được cho chẩn đoán mà không sinh lại |
| B7 | Thêm vào ablation cấu hình C5 = C4 + B2–B4 | `eval/v2/run_ablation.py`, `config.yaml` | Bảng C0, C1, C4, C5 |

### C. Dữ liệu người học (P0)

| # | Việc | File | Xong khi |
| --- | --- | --- | --- |
| C1 | Bảng `users` tối thiểu (tên hiển thị, mã), đăng nhập đơn giản bằng tên/mã ở UI | migration `003`, `models.py`, `ui/views/left.py` | Bài làm gắn `user_id` |
| C2 | Bảng `responses`: attempt, user, question, chữ cái đã chọn, đúng/sai, `error_type`, `candidate_id`, thời gian làm | migration `003`, `models.py` | Một dòng cho mỗi câu trả lời |
| C3 | `submit_attempt` ghi `responses` (tra `option_meta`) | `app/api/attempts.py`, `schemas.py` | Nộp bài sinh đủ dòng `responses` |
| C4 | UI ghi thời gian từng câu (tuỳ chọn) | `ui/views/quiz.py`, `state.py` | Có `time_ms` |

### D. Chẩn đoán và cá nhân hoá (P1)

| # | Việc | File | Xong khi |
| --- | --- | --- | --- |
| D1 | Màn hình xem lại: chọn sai thì hiện "Bạn có thể đang nhầm: …" theo loại lỗi (mô tả từ B1) | `attempts.py` (`ReviewItem` thêm `misconception`), `ui/views/quiz.py` | Hiện đúng loại lỗi của phương án đã chọn |
| D2 | Chatbot nhận loại hiểu nhầm khi mở hội thoại từ câu sai, giải thích nhắm đúng hiểu nhầm | `app/chat/answerer.py`, `chat_system.txt` | Câu trả lời đề cập hiểu nhầm và trích slide |
| D3 | Hồ sơ hiểu nhầm: đếm theo (người học, khái niệm, loại lỗi), có giảm dần theo thời gian | mới `app/learner/profile.py`, API `GET /users/{id}/profile` | Trả về top hiểu nhầm và khái niệm yếu |
| D4 | Ước lượng độ khó ban đầu của câu từ `selection.margin`, entropy, Bloom và cos trung bình của đáp án nhiễu với key | mới `app/learner/difficulty.py`; cột `questions.difficulty_est` | Mọi câu có độ khó Dễ/TB/Khó |
| D5 | Tạo đề theo mức độ khó | `quiz_sampler.py`, `schemas.py` (`difficulty`), `ui/views/center.py` | Chọn được mức độ ở UI |
| D6 | Chế độ "Luyện điểm yếu": ưu tiên khái niệm yếu và câu có đáp án nhiễu cùng loại lỗi người học hay mắc | `quiz_sampler.py` | Đề luyện khác đề thường, có lý do chọn từng câu |
| D7 | Elo cho người học và câu hỏi; chế độ "Tự động" chọn câu có xác suất đúng 70–80% | `app/learner/elo.py`, cột `questions.difficulty_elo`, bảng `user_skill` | Elo cập nhật sau mỗi lần nộp |
| D8 | Bản đồ thành thạo theo khái niệm/chương ở UI | `ui/views/left.py` hoặc trang mới | Người học thấy khái niệm vững và yếu |

### E. Phân tích câu hỏi và tự cải thiện ngân hàng (P1)

| # | Việc | File | Xong khi |
| --- | --- | --- | --- |
| E1 | Thống kê từng câu: tỉ lệ đúng, độ phân biệt (nhóm 27% trên/dưới), tỉ lệ chọn từng đáp án nhiễu | mới `app/learner/item_analysis.py`, API cho giảng viên | Bảng thống kê theo câu |
| E2 | Đánh dấu đáp án nhiễu kém: không ai chọn sau ≥ 20 lượt, hoặc được chọn nhiều hơn đáp án đúng ở nhóm giỏi | `item_analysis.py` | Danh sách cần sửa |
| E3 | Sinh lại đáp án nhiễu bị đánh dấu, dùng lại `step_distractors` kèm danh sách tránh và loại lỗi còn thiếu | `pipeline_v2.py` (hàm mới `regenerate_distractor`) | Đáp án nhiễu mới được lưu, lịch sử giữ lại |
| E4 | Hiệu chỉnh `difficulty_est` theo tỉ lệ đúng thực tế (IRT khi đủ dữ liệu, thư viện `girth` hoặc `py-irt`) | `difficulty.py` | Độ khó cập nhật từ dữ liệu |
| E5 | Thống kê cho giảng viên: "x% lớp nhầm khái niệm A với B" | API + trang UI | Có bảng hiểu nhầm phổ biến |

### F. Dạng câu hỏi mới (P2)

Thiết kế chung: `questions` thêm `qtype` (`mcq` | `order` | `gap_match` | `match` | `hottext`) và `payload JSONB`. Dạng `mcq` giữ nguyên các cột cũ.

| # | Việc | Nguồn dữ liệu sẵn có | File |
| --- | --- | --- | --- |
| F1 | Schema `qtype` + `payload`, chấm điểm từng dạng (cho điểm từng phần) | — | migration `004`, `schemas.py`, `attempts.py` |
| F2 | Sắp xếp thứ tự các bước | `answer_type = buoc_quy_trinh` | prompt `q_order.txt`, `bank_builder.py` |
| F3 | Kéo thả điền khuyết: bỏ trống 2–4 thuật ngữ; ngân hàng từ gồm đáp án và đáp án nhiễu đã qua lọc | ứng viên trong `distractor_candidates` | prompt `q_gap.txt` |
| F4 | Nối khái niệm ↔ định nghĩa/ví dụ trong cùng chương, thêm 1–2 vế thừa | `answer_type = thuat_ngu / so_sanh` | prompt `q_match.txt` |
| F5 | Tìm lỗi sai: đoạn đúng được cài 1–2 lỗi bằng đáp án nhiễu đã có loại lỗi | đáp án nhiễu + `error_type` | prompt `q_hottext.txt` |
| F6 | Giao diện kéo thả và sắp xếp (kiểm tra component `streamlit-sortables`) | — | `ui/views/quiz.py` |
| F7 | Mở rộng hồ sơ hiểu nhầm cho dạng mới (vế nối sai, bước đặt sai, lỗi bỏ sót) | — | `profile.py` |

### G. Đánh giá và báo cáo (P0 cho G1–G3)

| # | Việc | Xong khi |
| --- | --- | --- |
| G1 | Chạy lại `eval/quality` với V1, V2, V3 (C5) trên cùng tập hạt giống; báo cáo CI 95% bằng bootstrap | Bảng so sánh mới, thay báo cáo 08/11 |
| G2 | Người chấm: chấm lại đáp án nhiễu của V1 và V3 theo quy trình `eval/mcq`, không biết câu thuộc phiên bản nào | Điểm "hợp lý" và "chắc chắn sai" kèm CI |
| G3 | Kiểm tra nhãn hiểu nhầm: 2 người gán nhãn độc lập khoảng 60 đáp án nhiễu, tính kappa giữa người và với LLM | Kappa người–người, người–LLM |
| G4 | Thử nghiệm với sinh viên: 10–20 người, ít nhất 2 đề; đo độ phân biệt, tỉ lệ chọn đáp án nhiễu, và tỉ lệ đúng theo mức độ khó | Bảng item analysis thật |
| G5 | Kiểm tra vòng cá nhân hoá: người học làm đề luyện điểm yếu sau đề thường; so sánh tỉ lệ mắc cùng loại lỗi trước và sau | Số liệu trước/sau (thử nghiệm nhỏ, nêu hạn chế) |
| G6 | Cập nhật `README.md`, `docs/tong-quan-he-thong.md`, `docs/so-do-he-thong.html` và chương phương pháp/thực nghiệm | Tài liệu khớp với code |

## 5. Thay đổi cơ sở dữ liệu

**Migration `003_v3.sql`** (dạng `IF NOT EXISTS`, chạy lại được):

| Thay đổi | Nội dung |
| --- | --- |
| `questions` thêm cột | `option_meta JSONB`, `difficulty_est TEXT`, `difficulty_elo REAL DEFAULT 1200`, `concept TEXT` (lấy từ `key_point`) |
| Bảng mới `users` | id, display_name, code, created_at |
| `attempts` thêm cột | `user_id`, `mode` (`normal` / `difficulty` / `weakness` / `auto`) |
| Bảng mới `responses` | attempt_id, user_id, question_id, chosen, is_correct, candidate_id, error_type, time_ms |
| Bảng mới `user_skill` | user_id, concept, elo, mastery, updated_at |
| Bảng mới `misconception_stats` | user_id, concept, error_type, count, last_seen |

**Migration `004_qtypes.sql`** (P2): `questions.qtype`, `questions.payload JSONB`; nới ràng buộc `answer CHAR(1)` cho dạng không phải `mcq`.

## 6. Cấu hình mới (`config.yaml`)

```yaml
distractor:
  llm_candidates: 5
  tag_errors: true              # B2
  min_error_types: 2            # B4
  neighbor_concepts: 3          # B3

learner:
  difficulty_levels: {easy: [0.5, 1.0], medium: [0.25, 0.5], hard: [0.0, 0.25]}   # theo selection.margin, sẽ hiệu chỉnh
  elo_k: 24
  target_p_correct: [0.7, 0.8]
  weakness_decay_days: 14
  min_responses_for_analysis: 20
```

## 7. Ngoài phạm vi và rủi ro

**Ngoài phạm vi:** fine-tune lại ViT5 hoặc thêm BARTpho; tối ưu prompt tự động bằng DSPy; hotspot trên hình slide; xuất H5P/QTI.

| Rủi ro | Cách xử lý |
| --- | --- |
| ViT5 không sửa được hoặc đóng góp rất ít | Tắt nguồn ViT5, giữ nó là một kết quả âm trong báo cáo; v3 vẫn chạy với LLM |
| LLM gắn nhãn hiểu nhầm sai | Đo kappa (G3); nhãn kém thì giảm số loại lỗi hoặc thêm ví dụ vào `misconception_types.json` |
| Không đủ người học thật | Cá nhân hoá chỉ demo được chức năng; ghi rõ hạn chế; G4 tối thiểu 10 người |
| Tăng ứng viên làm chậm thêm | Bù bằng A5; sinh ngân hàng chạy nền nên người dùng không phải chờ |
| Độ khó ước lượng ban đầu không khớp thực tế | Hiệu chỉnh bằng E4; báo cáo tương quan giữa độ khó ước lượng và tỉ lệ đúng |
| Streamlit hạn chế kéo thả | Dùng component cộng đồng; nếu không ổn thì dùng dropdown thay cho kéo thả |

## 8. Thứ tự thực hiện đề xuất

```text
A (đo lại, sửa nền) → B (đáp án nhiễu chẩn đoán) → C (dữ liệu người học)
   → G1–G3 (số liệu chất lượng) → D1–D6 (chẩn đoán, mức độ khó, luyện điểm yếu)
   → G4–G5 (thử nghiệm sinh viên) → E (tự cải thiện ngân hàng) → D7–D8 (Elo, bản đồ thành thạo)
   → F (dạng câu mới) → G6 (tài liệu)
```

A, B, C và G1–G3 là phần lõi. Hoàn thành chúng là đã có v3 khác biệt rõ với v2 và có số liệu chứng minh. Các hạng mục sau làm hệ thống đầy đủ hơn, nhưng không phải điều kiện để v3 có ý nghĩa.
