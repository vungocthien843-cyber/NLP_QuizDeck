# BÁO CÁO ĐÁNH GIÁ HỆ THỐNG SINH CÂU HỎI TRẮC NGHIỆM

Bộ đánh giá 3 tầng, định nghĩa từng độ đo: `docs/bo-danh-gia.md`. File này tạo tự động bởi `python -m eval.tong_hop` (`scripts\3_bao_cao_tong_hop.bat`); chạy lại sau mỗi lần có kết quả mới.

| Tầng | Trạng thái | Ghi chú |
|---|---|---|
| Tầng 1 tự động | ✅ có | lớp S/J đủ |
| Tầng 2 người chấm | ⏳ chờ phiếu |  |
| Tầng 3 sinh viên | ⏳ chưa thử nghiệm |  |

## Tầng 1: đánh giá tự động (bộ dữ liệu `data_nlp`, không cần người)

| Mã | Độ đo | V1 | V3 | LLM-GPT | Hiệu V3−mốc | Mục tiêu | Nguồn |
|---|---|---|---|---|---|---|---|
| M1 | **Open-book Solver Accuracy** | 1.000 ✅ | 0.990 ✅ | 0.980 ✅ | +0.010 (so LLM-GPT) | ≥ 0,95 | 20261117-163449, mẫu 5, 20261117-173521 |
| M1b | **Ambiguity Rate** | 0.000 ✅ | 0.170 ❌ | 0.010 ✅ | +0.160 * (so LLM-GPT) | ≤ 0,05 | 20261117-163449, mẫu 5, 20261117-173807 |
| M2 | **Choices-only Accuracy** | 0.800 (p=0.016) ❌ | 0.770 (p=0.000) ❌ | 0.820 (p=0.000) ❌ | -0.050 (so LLM-GPT) | ≈ 0,25 (p ≥ 0,05) | 20261117-163449, mẫu 5, 20261117-173521 |
| M3 | **Semantic Plausibility Rate** | 0.663 ❌ | 0.620 ❌ | 0.720 ✅ | -0.068 (so V1) | ≥ 0,70 | 20261117-171844 |
| M3b | **Off-topic Rate** | 0.064 ❌ | 0.067 ❌ | 0.053 ❌ | +0.010 (so V1) | ≤ 0,05 | 20261117-171844 |
| M4 | **Near-duplicate Rate** | 0.212 ❌ | 0.160 ❌ | 0.150 ❌ | -0.041 (so V1) | ≤ 0,10 | 20261117-171844 |
| M4b | **Distinct-2** | 0.799 | 0.806 | 0.853 | -0.047 * (so LLM-GPT) | cao | 20261117-171844, 20261117-173807 |
| M5 | **Longest-Key Rate** | 0.308 (p=0.175) ✅ | 0.168 (p=0.065) ✅ | 0.058 (p=0.000) ❌ | +0.110 * (so LLM-GPT) | ≈ 0,25 (p ≥ 0,05) | 20261117-171844, 20261117-173807 |
| M5b | **Shortest-Key Rate** | 0.225 (p=0.572) ✅ | 0.261 (p=0.818) ✅ | 0.694 (p=0.000) ❌ | -0.433 * (so LLM-GPT) | ≈ 0,25 (p ≥ 0,05) | 20261117-171844, 20261117-173807 |
| M6 | **Misconception Coverage** | không áp dụng | 0.960 ✅ | không áp dụng |  | ≥ 0,80 | 20261117-173807 |
| M5c | **Key-length Rank Uniformity** (χ² p; số câu theo hạng 0–3) | p=0.501 [23, 26, 22, 32] ✅ | p=0.121 [26, 34, 24, 17] ✅ | p=0.000 [69, 17, 8, 6] ❌ |  | p ≥ 0,05 | |

LLM-GPT / LLM-Gemini: đối chứng LLM trực tiếp — cùng slide, câu hỏi, đáp án đúng với V3, chỉ một lời gọi sinh 3 phương án nhiễu (không 7 kiểu hiểu nhầm, không lọc, không xếp hạng).
`*` = CI 95% của hiệu không chứa 0. Chi tiết, CI và kiểm định: report.md của lần chạy ở cột Nguồn.
Lớp S/J: giám khảo `openai/gpt-6-sol`, người giải ['gemini/gemini-flash-latest', 'gemini/gemini-flash-lite-latest'].

### Ablation (cùng kho ứng viên, chọn lại không sinh lại)

| Độ đo | V3-chi-ViT5 | V3-chi-LLM | V3 |
|---|---|---|---|
| M3 Semantic Plausibility Rate | 0.614 | 0.614 | 0.620 |
| M4 Near-duplicate Rate | 0.295 | 0.110 | 0.160 |
| M4b Distinct-2 | 0.793 | 0.796 | 0.806 |
| M5 Longest-Key Rate | 0.509 | 0.098 | 0.168 |
| M5b Shortest-Key Rate | 0.085 | 0.402 | 0.261 |
| M6 Misconception Coverage | 0.500 | 0.951 | 0.960 |

V2-random / V2-top3 / V2-no-delta: cách chọn bộ 3 (ngẫu nhiên, 3 điểm cao nhất, entropy không δ). V3-chi-ViT5 / V3-chi-LLM: chỉ dùng ứng viên của một nguồn sinh.

## Tầng 2: người chấm (G2 chất lượng câu, G3 nhãn hiểu nhầm)

_Chưa có. Phiếu đã gửi cho 2 người chấm; nhận lại thì chép vào `eval\human_v3\data` và chạy `scripts\6_phan_tich_phieu_nguoi.bat`._

## Tầng 3: sinh viên làm bài thật (G4 phân tích câu, G5 cá nhân hoá)

_Chưa có. Chạy `scripts\7_thu_nghiem_sv_chuan_bi.bat`, tổ chức buổi thử nghiệm (kịch bản: `eval\student\kich_ban_thu_nghiem.md`), rồi `scripts\8_thu_nghiem_sv_phan_tich.bat`._
