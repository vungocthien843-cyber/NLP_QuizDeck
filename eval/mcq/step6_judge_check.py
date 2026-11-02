"""Bước 6: đo độ tin cậy của chính judge, trước khi dùng số liệu của nó. Tốn API.

- So với người: precision, recall khi đánh dấu câu lỗi (cần phieu_chot.csv đã chốt ở bước 4).
- Cài lỗi: thay nội dung phương án đúng bằng đáp án của câu ở tài liệu khác. Câu không còn đáp án đúng, judge phải chọn NONE.
- Sai ngữ cảnh: đưa slide của tài liệu khác, judge phải chọn NONE.
- Ổn định: chạy lại đúng câu cũ, so với kết quả ở bước 5.

Chạy: python -m eval.mcq.step6_judge_check [--n 30]
"""
import argparse
import asyncio
import json
import random

from app.config import get_config
from eval.mcq.common import (
    DEFAULT_SEED,
    RESULTS_DIR,
    SAMPLE_KEY,
    SHEET_FINAL,
    ask_judge,
    context_of,
    fail,
    load_chunks,
    load_questions,
    read_csv,
    wilson,
    write_csv,
)
from eval.mcq.step4_agreement import parse_final
from eval.mcq.step5_judge import load_runs, question_rng


def flag_metrics(flagged: list[bool], human_bad: list[bool]) -> dict:
    """Lớp dương là câu lỗi. flagged[i]: judge đánh dấu câu i; human_bad[i]: người chấm kết luận câu i lỗi."""
    tp = sum(f and h for f, h in zip(flagged, human_bad, strict=True))
    fp = sum(f and not h for f, h in zip(flagged, human_bad, strict=True))
    fn = sum(not f and h for f, h in zip(flagged, human_bad, strict=True))
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def plant_wrong_option(question: dict, others: list[dict], rng: random.Random) -> tuple[dict[str, str], str]:
    """Thay phương án đúng bằng đáp án đúng của một câu khác; trả (phương án mới, nội dung đã cài)."""
    donor = rng.choice(others)
    planted = donor["options"][donor["answer"]]
    return {**question["options"], question["answer"]: planted}, planted


def human_verdicts() -> dict[int, bool] | None:
    """question_id → đạt. None nếu chưa chốt xong phiếu."""
    if not SHEET_FINAL.exists():
        return None
    verdicts = parse_final(read_csv(SHEET_FINAL))
    if verdicts is None:
        return None
    ids = {k["ma_cau"]: int(k["question_id"]) for k in read_csv(SAMPLE_KEY)}
    return {ids[code]: ok for code, ok in verdicts.items()}


async def gather_limited(tasks: list, limit: int) -> list:
    sem = asyncio.Semaphore(limit)

    async def one(task):
        async with sem:
            try:
                return await task
            except Exception as exc:
                return {"choice": "ERROR", "reason": str(exc)}

    return await asyncio.gather(*(one(t) for t in tasks))


def proportion_row(name: str, ok: int, n: int, note: str) -> dict:
    low, high = wilson(ok, n)
    return {"tieu_chi": name, "gia_tri": round(ok / n, 3) if n else "", "ghi_chu": f"{ok}/{n}, KTC 95%: {low:.2f}–{high:.2f}. {note}"}


async def run_tests(base: list[dict], questions: list[dict], chunks: dict[int, dict], runs: dict[int, dict],
                    seed: int) -> tuple[list[dict], list[dict]]:
    limit = get_config().bank.concurrency
    rng = random.Random(seed)
    rows: list[dict] = []
    details: list[dict] = []

    def record(test: str, q: dict, result: dict) -> dict:
        entry = {"phep_thu": test, "question_id": q["id"], "choice": result["choice"], "reason": result.get("reason", "")}
        details.append(entry)
        return entry

    def valid(results: list[dict]) -> list[dict]:
        return [r for r in results if r["choice"] != "ERROR"]

    # Cài lỗi
    tasks, planted_texts = [], []
    for q in base:
        others = [o for o in questions if o["document_id"] != q["document_id"]] or [o for o in questions if o["id"] != q["id"]]
        options, planted = plant_wrong_option(q, others, rng)
        planted_texts.append(planted)
        tasks.append(ask_judge(q["stem"], options, context_of(q, chunks), question_rng(seed, q["id"])))
    results = await gather_limited(tasks, limit)
    for q, r in zip(base, results, strict=True):
        record("cai_loi", q, r)
    good = valid(results)
    fooled = sum(r["choice"] == q["answer"] for q, r in zip(base, results, strict=True))
    rows.append(proportion_row("cai_loi_chon_NONE", sum(r["choice"] == "NONE" for r in good), len(good), "Càng cao càng tốt."))
    rows.append(proportion_row("cai_loi_chon_phuong_an_gia", fooled, len(good), "Càng thấp càng tốt."))

    # Sai ngữ cảnh
    by_document: dict[int, list[dict]] = {}
    for chunk in chunks.values():
        by_document.setdefault(chunk["document_id"], []).append(chunk)
    tasks = []
    for q in base:
        pool = [c for doc, group in by_document.items() if doc != q["document_id"] for c in group]
        pool = pool or [c for c in chunks.values() if c["id"] not in q["source_chunk_ids"]]
        tasks.append(ask_judge(q["stem"], q["options"], rng.sample(pool, min(2, len(pool))), question_rng(seed, q["id"])))
    results = await gather_limited(tasks, limit)
    for q, r in zip(base, results, strict=True):
        record("sai_ngu_canh", q, r)
    good = valid(results)
    rows.append(proportion_row("sai_ngu_canh_chon_NONE", sum(r["choice"] == "NONE" for r in good), len(good), "Càng cao càng tốt."))

    # Ổn định: dùng đúng thứ tự xáo như bước 5
    stable_base = [q for q in base if q["id"] in runs]
    tasks = [ask_judge(q["stem"], q["options"], context_of(q, chunks), question_rng(seed, q["id"])) for q in stable_base]
    results = await gather_limited(tasks, limit)
    for q, r in zip(stable_base, results, strict=True):
        record("on_dinh", q, r)
    pairs = [(q, r) for q, r in zip(stable_base, results, strict=True) if r["choice"] != "ERROR"]
    same = sum(r["choice"] == runs[q["id"]]["choice"] for q, r in pairs)
    rows.append(proportion_row("on_dinh_giong_lan_truoc", same, len(pairs), "Càng cao càng tốt."))
    return rows, details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30, help="Số câu cho mỗi phép thử")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    runs = load_runs()
    if not runs:
        fail("chưa có kết quả judge. Chạy trước: python -m eval.mcq.step5_judge")
    questions = [q for q in load_questions() if q["status"] == "accepted"]
    chunks = load_chunks()
    rows: list[dict] = []

    verdicts = human_verdicts()
    if verdicts is None:
        print("Chưa có phieu_chot.csv đã chốt: tạm bỏ qua phần so với người, và lấy mẫu từ các câu judge đã đồng ý.")
        pool = [q for q in questions if runs.get(q["id"], {}).get("verdict") == "dong_y"]
    else:
        pool = [q for q in questions if verdicts.get(q["id"])]
        pool = pool if len(pool) >= args.n else pool + [q for q in questions if runs.get(q["id"], {}).get("verdict") == "dong_y"
                                                        and q["id"] not in {p["id"] for p in pool}]
        judged = [q["id"] for q in questions if q["id"] in verdicts and q["id"] in runs]
        metrics = flag_metrics([runs[i]["verdict"] != "dong_y" for i in judged], [not verdicts[i] for i in judged])
        note = f"TP={metrics['tp']}, FP={metrics['fp']}, FN={metrics['fn']} trên {len(judged)} câu accepted đã chấm"
        rows.append({"tieu_chi": "so_voi_nguoi_precision", "gia_tri": "" if metrics["precision"] is None else round(metrics["precision"], 3), "ghi_chu": note})
        rows.append({"tieu_chi": "so_voi_nguoi_recall", "gia_tri": "" if metrics["recall"] is None else round(metrics["recall"], 3),
                     "ghi_chu": f"{note}. Ít câu lỗi thì recall dao động mạnh."})

    base = random.Random(args.seed).sample(pool, min(args.n, len(pool)))
    print(f"Chạy 3 phép thử trên {len(base)} câu, tối đa {3 * len(base)} lượt gọi {get_config().models.judge_independent}.")
    test_rows, details = asyncio.run(run_tests(base, questions, chunks, runs, args.seed))
    rows += test_rows

    errors = sum(d["choice"] == "ERROR" for d in details)
    with (RESULTS_DIR / "judge_check.jsonl").open("w", encoding="utf-8") as f:
        for entry in details:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    path = RESULTS_DIR / "danh_gia_judge.csv"
    write_csv(path, rows)
    for row in rows:
        print(f"  {row['tieu_chi']}: {row['gia_tri']}  {row['ghi_chu']}")
    if errors:
        print(f"Có {errors} lượt lỗi, không tính vào kết quả. Xem judge_check.jsonl.")
    print(f"Đã ghi: {path}")


if __name__ == "__main__":
    main()
