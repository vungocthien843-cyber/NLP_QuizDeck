# Bộ đánh giá hệ thống sinh câu hỏi trắc nghiệm (bản hoàn chỉnh, 17/11/2026)

## 1. Nguyên tắc thiết kế

- **Không cần tham chiếu (reference-free).** Đồ án sinh câu từ slide, không có bộ câu hỏi chuẩn do giáo viên viết. Vì vậy **không dùng** BLEU, ROUGE, METEOR, BERTScore hay Exact Match/F1 với phương án nhiễu của giáo viên làm độ đo chính.
  - Các độ đo này cần câu mẫu.
  - Chúng phạt cả câu tốt nhưng khác câu mẫu.
  - Exact Match còn phạt đúng điểm mạnh của V3 (phương án nhiễu mới, hợp lý).
- **Ba tầng, từ rẻ đến sát thực tế.** Kết luận chính dựa trên Tầng 1 (toàn bộ 100 slide). Tầng 2 và Tầng 3 kiểm chứng trên mẫu nhỏ hơn, cho biết độ đo tự động có đi cùng chiều với người hay không.

| Tầng | Ai chấm | Phạm vi | Chi phí |
|---|---|---|---|
| 1. Tự động | Luật, embedding bge-m3, LLM khác họ làm người giải và giám khảo | Toàn bộ câu G1 (V1 97, V2 93, V3 93) và các biến thể ablation | Lớp A, E: 0. Lớp S, J: Gemini miễn phí (chậm) hoặc OpenAI (khoảng 1–5 USD) |
| 2. Người chấm | Bùi Minh Ảnh, Lê Đình Trung; chấm mù, độc lập | 40 cặp V1–V3 (80 câu, 240 phương án sai) và 60 nhãn hiểu nhầm | Khoảng 3 giờ mỗi người |
| 3. Sinh viên | 10–20 sinh viên làm bài thật | 2 đề × 15 câu, thiết kế đối trọng V1/V3 | Một buổi khoảng 60 phút |

- **So sánh có kiểm soát.**
  - V1 là **baseline**: một lần gọi LLM, đúng cách làm phổ biến.
  - Mọi phiên bản sinh từ **cùng 100 slide hạt giống**. Hiệu số được tính theo cặp cùng slide, kèm **CI 95% bootstrap theo chunk**.
  - Ablation chọn lại trên **cùng kho ứng viên**, không sinh lại, để tách đóng góp của từng thành phần.

## 1b. Dữ liệu dùng để chấm

| Bộ | Nội dung | Trạng thái |
|---|---|---|
| **NLP** (chính, từ 17/11) | **Toàn bộ 9 chương NLP** (các bài có tên file chứa "Chuong"), **12 slide hạt giống mỗi chương** (~108), rải đều trong mỗi chương. Bỏ slide tiêu đề và slide hành chính (lộ trình, mục tiêu, tài liệu tham khảo, cảm ơn). Mỗi slide sinh 1 câu ở V1 (C0) và V3 (C5); **bỏ V2** (quyết định 17/11, mất ablation V1→V2→V3 và ablation cách chọn bộ 3, giữ ablation nguồn sinh). Kết quả: `eval/v2/results/NLP` → `eval/quality/data_nlp` | Tạo bằng `scripts\_da_chay\2b_tao_bo_danh_gia_NLP.bat` (1–1,5 giờ) |
| G1 (15/11) | 100 slide của bài 17 (NLP chương 4), 4 (Thị giác máy tính bài 1) và 22 (NLP chương 9). **Lệch**: chương 9 chỉ được 2 slide, do `pick_seeds` cắt `seeds[:n]` sau khi rải theo thứ tự bài (lỗi đã sửa bằng chế độ chia đều `--per-doc`) | Đã có. Phiếu người chấm ngày 16/11 dùng bộ này |

Mọi phiên bản sinh trên **cùng** các slide hạt giống, và mỗi độ đo được so theo cặp cùng slide. Các file `scripts\3`, `3b`, `4`, `6` tự dùng bộ NLP khi bộ này đã có.

## 2. Tầng 1: 6 độ đo chính tự động (`eval/quality/core.py`)

| Mã | Tên chuẩn | Câu hỏi trả lời | Công thức | Mục tiêu |
|---|---|---|---|---|
| **M1** | **Open-book Solver Accuracy** | Câu có đúng và trả lời được không? | $\frac{1}{N}\sum_i \mathbb{1}[\hat y_i = y_i]$, trong đó người giải LLM được xem slide | ≥ 0,95 |
| M1b | Ambiguity Rate | Có câu nào ≥ 2 đáp án đúng không? | Tỉ lệ câu giám khảo LLM đánh ≥ 2 phương án "correct" | ≤ 0,05 |
| **M2** | **Choices-only Accuracy** | Có đoán mò được không? | Như M1 nhưng người giải **chỉ thấy 4 phương án**, không thấy câu hỏi; kiểm định nhị thức hai phía so với 0,25 | ≈ 0,25 (p ≥ 0,05) |
| **M3** | **Semantic Plausibility Rate** | Phương án nhiễu có gần mà không trùng đáp án đúng không? | $\frac{1}{\lvert D\rvert}\sum_d \mathbb{1}[a \le \cos(e_d, e_{key}) \le b]$, với [a, b] = [0,5; 0,85] (bge-m3) | ≥ 0,70 |
| M3b | Off-topic Rate | Phương án nhiễu có lạc đề không? | Tỉ lệ phương án nhiễu có cos(d, slide) < τ; τ tự hiệu chỉnh bằng trung vị cos giữa phương án nhiễu và slide của câu khác | ≤ 0,05 |
| **M4** | **Near-duplicate Rate** | 3 phương án nhiễu có trùng ý nhau không? | Tỉ lệ câu có cặp phương án nhiễu với cos > 0,9 | ≤ 0,10 |
| M4b | Distinct-2 | Đa dạng về từ ngữ | Số bigram âm tiết khác nhau / tổng số bigram của 3 phương án nhiễu | cao |
| **M5** | **Longest-Key Rate** | Có lộ đáp án qua độ dài không? | Tỉ lệ câu có đáp án đúng nhiều từ nhất (hoà thì chia đều); kiểm định nhị thức so với 0,25 | ≈ 0,25 (p ≥ 0,05) |
| M5b | Shortest-Key Rate | (chiều ngược lại) | Như M5, xét phương án ngắn nhất | ≈ 0,25 |
| M5c | Key-length Rank Uniformity | Hạng độ dài của đáp án đúng có phân bố đều không? | χ² với phân bố đều trên 4 hạng, 3 bậc tự do | p ≥ 0,05 |
| **M6** | **Misconception Coverage** | Bộ 3 có chẩn đoán được không? (riêng V3) | Tỉ lệ câu mà 3 phương án nhiễu phủ ≥ 2 loại hiểu nhầm khác nhau (trừ `khong_ro`) | ≥ 0,80 |

Kèm theo: **Generation Yield** = số câu đạt / số hạt giống.

### Lý do chọn từng độ đo

- **M1** thay cho tiêu chí "câu dùng được, đúng một đáp án" của người chấm, và phát hiện đáp án sai.
- **M2** là phép thử "đoán mò" tổng quát. Một độ đo này bao mọi loại mẹo: độ dài, trùng từ, điểm hội tụ, cách viết.
- **M3** cụ thể hoá "cosine similarity vừa phải" thành tỉ lệ nằm trong dải, dễ đọc.
- **M4** là độ đo đa dạng: hai phương án nhiễu trùng ý thì câu thực chất chỉ còn 3 lựa chọn.
- **M5** đo lỗi kinh điển "đáp án đúng dài nhất", tính tức thì và dễ giải thích.
- **M6** đo đóng góp riêng của V3: chẩn đoán được người học đang nhầm gì.

M1 và M2 có thể chạy bằng Gemini (miễn phí) hoặc OpenAI gpt-6-sol. Cả hai đều khác model sinh câu (gpt-6-luna). Nếu dùng OpenAI thì phải ghi rõ trong phần hạn chế là cùng hãng với model sinh.

**Hạn chế:**
- M3 và M4 là độ đo **gián tiếp** (hình học vector).
- M1 và M2 là **LLM đóng vai người làm bài**.
- M6 dùng nhãn do chính LLM gắn: **chỉ mô tả**. Độ tin cậy của nhãn được đo ở Tầng 2 (H5).

### Ablation (cùng kho ứng viên, không sinh lại)

| Biến thể | Câu hỏi |
|---|---|
| V2-random / V2-top3 / V2-no-delta / V2 | Cách chọn bộ 3 có tác dụng không? (ngẫu nhiên / 3 điểm cao nhất / entropy không δ / entropy + δ + ràng buộc) |
| V3-chi-ViT5 / V3-chi-LLM / V3 | Cần cả mô hình fine-tune lẫn LLM không? |

## 3. Tầng 2: người chấm (`eval/human_v3`)

| Mã | Tên | Cách tính | Mục tiêu |
|---|---|---|---|
| **H1** | **Item Validity Rate** | Tỉ lệ câu đạt cả 3 tiêu chí 0/1 (đúng kiến thức, một đáp án đúng, tự đứng được); trung bình 2 người | ≥ 0,80 |
| **H2** | **Distractor Plausibility** | Điểm trung bình (thang Likert 1–5) của từng phương án nhiễu | ≥ 3,5 |
| H3 | Misconception Expression Rate | Tỉ lệ phương án nhiễu "thể hiện một kiểu hiểu nhầm gọi tên được" | V3 > V1 |
| H4 | Non-ambiguity | Tỉ lệ câu có đúng một đáp án đúng | ≥ 0,90 |
| **H5** | **Cohen's κ** (người–người, người–LLM) cho nhãn hiểu nhầm, cùng accuracy và precision/recall theo loại | $\kappa = \frac{p_o - p_e}{1 - p_e}$ | κ người–LLM ≥ 0,4 và gần κ người–người |

**Phương pháp:**
- Chấm mù, không biết câu thuộc phiên bản nào. So V1 với V3 theo cặp cùng slide: hiệu số, CI bootstrap, kiểm định Wilcoxon.
- Độ đồng thuận giữa 2 người: Cohen's κ cho tiêu chí 0/1; weighted κ (bậc hai) cho thang 1–5.

## 4. Tầng 3: sinh viên (`eval/student`)

| Mã | Tên | Cách tính | Mục tiêu |
|---|---|---|---|
| T1 | Difficulty Index p | Tỉ lệ làm đúng | 0,3–0,8 |
| **T2** | **Discrimination Index D** | $D = p_U - p_L$, với nhóm 27% điểm cao và 27% điểm thấp (Kelley) | ≥ 0,3 (Ebel) |
| T3 | Point-biserial r_pb | $r_{pb} = \frac{M_1 - M_0}{s}\sqrt{pq}$, so với điểm phần còn lại của bài | ≥ 0,2 |
| **T4** | **NFD%** (Non-Functioning Distractor) | Tỉ lệ phương án nhiễu được < 5% người chọn (Haladyna & Downing) | < 0,20 |
| T5 | Diagnosis Agreement | Tỉ lệ sinh viên trả lời "đúng" hoặc "một phần" cho câu hỏi chẩn đoán có khớp suy nghĩ không | cao |
| G5 | Cá nhân hoá | Nhóm A so với B: tiến bộ, tỉ lệ sửa được lỗi cũ, tỉ lệ lặp lại hiểu nhầm cũ | chỉ mô tả |

## 5. Cách chạy

| Việc | File | Kết quả |
|---|---|---|
| **Tạo bộ dữ liệu NLP 9 chương** + lớp A + E | `scripts\_da_chay\2b_tao_bo_danh_gia_NLP.bat` | `eval/v2/results/NLP`, `eval/quality/data_nlp`, báo cáo tổng hợp |
| Đối chứng LLM trực tiếp + Tầng 1 lớp A + E (miễn phí) | `scripts\1_sinh_doi_chung_llm.bat` | `eval/quality/data_nlp/LLM-*_items.jsonl`, `eval/quality/results/<thời điểm>/report.md` |
| Tầng 1, lớp S + J (V3 so với LLM-GPT, có trần chi phí) | `scripts\2_cham_openai.bat` | như trên, kèm `chi_phi.txt` |
| Tầng 2 | Phiếu đã gửi → `scripts\6_phan_tich_phieu_nguoi.bat` | `eval/human_v3/results/` |
| Tầng 3 | `scripts\6_…` → buổi thử nghiệm → `scripts\7_…` | `eval/student/results/` |
| **Báo cáo tổng hợp** | `scripts\3_bao_cao_tong_hop.bat` | **`eval/BAO_CAO_DANH_GIA.md`**, gom cả 3 tầng; tầng nào chưa có thì ghi việc cần làm |

## 6. Kết quả hiện có (bộ G1, Tầng 1, lớp A + E, 15/11; sẽ thay bằng bộ NLP)

| Mã | V1 | V3 | Hiệu |
|---|---|---|---|
| M4b Distinct-2 | 0,780 | 0,819 | +0,040 |
| M5 Longest-Key Rate | 0,395 ❌ | 0,142 ❌ | −0,259 * |
| M5b Shortest-Key Rate | 0,155 ❌ | 0,288 ✅ | +0,111 * |
| M5c χ² p (hạng độ dài đều) | 0,007 ❌ | 0,101 ✅ | |
| M6 Misconception Coverage | không áp dụng | 0,925 ✅ | |
| M3 Semantic Plausibility (lớp E) | 0,680 | 0,685 | |
| M4 Near-duplicate (lớp E) | 0,165 | 0,151 | |

M1, M2 (lớp S) và M1b (lớp J) chưa có đủ dữ liệu.
