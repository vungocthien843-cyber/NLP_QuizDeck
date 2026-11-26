# Huấn luyện mô hình sinh đáp án nhiễu (phiên bản 2)

Fine-tune **ViT5-base** để sinh nhiều ứng viên đáp án nhiễu cho một câu trắc nghiệm, áp dụng kỹ thuật của
Chung et al. 2020. Kế hoạch đầy đủ: `docs/ke-hoach-v2.md`.

```
training/
├── prepare_data.py              # chuẩn hoá VSMRC / ViMMRC / ngân hàng câu hỏi → JSONL (chạy trên máy)
├── export_bank.py               # xuất ngân hàng câu hỏi từ DB cho giai đoạn 2 (chạy trong container API)
├── common.py                    # hàm dùng chung của prepare_data
├── kaggle/train_ddp.py          # script huấn luyện torchrun + DDP, chia khối (nguồn của notebook)
├── notebooks/kaggle_train_ddp.ipynb   # notebook Kaggle: các cell %%writefile ghép thành train_ddp.py
├── data/raw/, data/processed/   # dữ liệu (không đưa vào git)
└── tests/
```

`train_ddp.py` viết theo thứ tự khối: Imports → Run utils → RuntimeEnv → Configs → Data → Model → Loss →
Callbacks → Trainer → Evaluator → Loaders → Plotting → main. Notebook được dựng từ đúng file này, mỗi khối là
một cell; sửa code thì sửa `train_ddp.py` rồi dựng lại notebook.

| Kỹ thuật | Khối trong `train_ddp.py` |
| --- | --- |
| K1 – unlikelihood trên token nội dung của đáp án đúng | Data (`DataProcessor.encode`), Loss (`UnlikelihoodLoss`) |
| K2 – quét hệ số λ | cell quét trong notebook (`--set training.lam=…`) |
| K3 – sinh nhiều ứng viên bằng diverse beam search | Evaluator (`GenerationEvaluator`) |
| K5 – tỉ lệ chép đáp án, BLEU/ROUGE-L đa tham chiếu | Evaluator (`GenerationEvaluator.score`) |

K4 (chọn bộ 3 bằng entropy có ràng buộc) nằm trong pipeline của API: `app/generation/selector.py`.

## Quy trình

1. **Chuẩn hoá dữ liệu** (đã chạy, kết quả ở `data/processed/`):
   `python -m training.prepare_data --vsmrc training/data/raw/vsmrc --out training/data/processed`
2. **Kaggle:** tải các file trong `data/processed/` lên thành một dataset, import
   `notebooks/kaggle_train_ddp.ipynb`, bật GPU T4 × 2 + Internet, chạy theo hướng dẫn ở đầu notebook.
3. **Kết quả** của mỗi lần chạy nằm trong `/kaggle/working/runs/<tên>/`:
   - `best_model/`: model dạng Hugging Face. Giải nén vào `checkpoints/dg-vit5-stage1/best` để API dùng.
   - `final_metrics.json`: chỉ số trên test và dev.
   - `logs/training_logs.csv`, `logs/run_rank_*.log`.
   - `training_curves.pdf`.
   - `last_checkpoint.pt`: để chạy tiếp.

Ghi đè cấu hình khi chạy: `torchrun --standalone --nproc_per_node=2 train_ddp.py --set training.lam=0.5 data.subset=0.3`.

## Lưu ý

- Gặp loss NaN khi chạy fp16 (họ T5 hay bị): `--set training.precision=fp32 training.batch_size=4`.
- Chạy tiếp qua nhiều phiên Kaggle: giữ cùng `logging.fixed_run_dir`, đưa thư mục `runs` của phiên trước vào
  làm Input (`RESUME_FROM`). Script tự nạp `last_checkpoint.pt`.
- Đánh giá sinh ứng viên mỗi epoch chạy trên rank 0 (`data.gen_eval_limit` câu), các rank khác đợi ở barrier.
- VSMRC do LLM (Gemini) sinh rồi được kiểm tra; cần nêu trong phần hạn chế của báo cáo.
- Kiểm thử: `pip install -r requirements/train.txt && python -m pytest -q training/tests` (~10 giây, không cần mạng).
