# Bộ đánh giá chất lượng câu trắc nghiệm (V1 so với V2)

Theo đặc tả `prompt_danh_gia_V1_V2.md`, điều chỉnh cho dự án:

- V2 của dự án không có bước chuẩn hoá và blind solver sinh lại, nên ablation không có hai biến thể đó. Thêm các
  biến thể riêng: chỉ ViT5 (`V2-vit5`), bỏ δ (`V2-no-delta`), chọn ngẫu nhiên (`V2-random`), top 3 (`V2-top3`).
- Chỉ có 1 người chấm: tính được độ đồng thuận judge–người, không tính được kappa giữa người chấm.

## Trạng thái

| Lớp | Nội dung | Trạng thái |
|---|---|---|
| Dữ liệu | `export.py`: kết quả `eval/v2/run_ablation` → `data/<phiên bản>_items.jsonl`, `yield.csv` | Xong |
| A (luật) | A1–A12, `metrics/rules.py` | Xong |
| A (embedding) | E1–E4, A13, `metrics/embed.py` (bge-m3) | Xong, cần container |
| Thống kê | bootstrap theo chunk, hiệu có CI, nhị thức, chi² (`stats.py`) | Xong |
| J, S | prompt P1–P8, `metrics/llm_eval.py`; mô hình đặt ở `config.yaml → eval_models` (khác họ với mô hình sinh), kết quả gọi được lưu đệm ở `cache/` | Xong code, cần chọn mô hình |
| Người chấm, judge–người | dùng lại quy trình `eval/mcq` | Chưa |

## Chạy (trong container API)

```bash
# 1. Sinh câu trên cùng hạt giống (chương 4 và 9 là tập test)
python -m eval.v2.run_ablation --docs 17 22 --n-seeds 60 --configs C0 C1 C4 --skip-solver
# 2. Xuất sang định dạng đánh giá
python -m eval.quality.export --results eval/v2/results/<thời điểm>
# 3. Tính chỉ số
python -m eval.quality.run_eval --layers A E
# 3b. Thêm lớp solver (S) và judge (J); chạy thử 10 câu trước để ước lượng chi phí
python -m eval.quality.run_eval --layers A S J --limit 10
python -m eval.quality.run_eval --layers A E S J
```

Kết quả ở `results/<thời điểm>/`: `report.md` (bảng tổng hợp, ablation, hạn chế), `summary.csv` (mỗi chỉ số kèm
CI 95%, phạm vi `all` và `common` = chỉ các chunk mà mọi phiên bản đều sinh được câu), `diff.csv` (hiệu so với V1),
`per_item_<phiên bản>.csv`, `set_level.csv` (A11–A13).
