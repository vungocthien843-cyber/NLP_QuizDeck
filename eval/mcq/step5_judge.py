"""Bước 5: judge làm lại mọi câu accepted khi có ngữ cảnh, đánh dấu câu nghi sai để người xem lại.
Không tự động loại câu nào. Tốn API. Chạy lại sẽ bỏ qua câu đã có kết quả.

Chạy thử: python -m eval.mcq.step5_judge --limit 5
Chạy hết: python -m eval.mcq.step5_judge
"""
import argparse
import asyncio
import json
import random

from app.config import get_config
from eval.mcq.common import (
    DEFAULT_SEED,
    JUDGE_RUNS,
    RESULTS_DIR,
    ask_judge,
    context_of,
    load_chunks,
    load_questions,
    write_csv,
)


def verdict_of(choice: str, answer: str) -> str:
    if choice == "NONE":
        return "none"
    return "dong_y" if choice == answer else "khac"


def question_rng(seed: int, question_id: int) -> random.Random:
    """Cố định thứ tự xáo cho từng câu, để hai lần chạy so sánh được với nhau."""
    return random.Random(f"{seed}:{question_id}")


def load_runs() -> dict[int, dict]:
    if not JUDGE_RUNS.exists():
        return {}
    with JUDGE_RUNS.open(encoding="utf-8") as f:
        return {r["question_id"]: r for r in map(json.loads, f) if r}


async def run(questions: list[dict], chunks: dict[int, dict], seed: int) -> tuple[int, list[str]]:
    sem = asyncio.Semaphore(get_config().bank.concurrency)
    errors: list[str] = []
    done = 0

    async def one(q: dict) -> None:
        nonlocal done
        async with sem:
            try:
                result = await ask_judge(q["stem"], q["options"], context_of(q, chunks), question_rng(seed, q["id"]))
            except Exception as exc:
                errors.append(f"câu {q['id']}: {exc}")
                return
        record = {"question_id": q["id"], "answer": q["answer"], "verdict": verdict_of(result["choice"], q["answer"]),
                  **result}
        with JUDGE_RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        done += 1

    await asyncio.gather(*(one(q) for q in questions))
    return done, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Chỉ chạy N câu chưa có kết quả, để thử output và chi phí")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    questions = [q for q in load_questions() if q["status"] == "accepted"]
    finished = load_runs()
    todo = [q for q in questions if q["id"] not in finished]
    if args.limit:
        todo = random.Random(args.seed).sample(todo, min(args.limit, len(todo)))

    print(f"Model: {get_config().models.judge_independent}. Cần chạy {len(todo)} câu, đã có {len(finished)} câu.")
    done, errors = asyncio.run(run(todo, load_chunks(), args.seed))
    print(f"Xong {done} câu, lỗi {len(errors)} câu.")
    for error in errors[:3]:
        print(f"  {error[:300]}")

    runs = load_runs()
    if not runs:
        raise SystemExit(1)
    by_id = {q["id"]: q for q in questions}
    counts = {v: sum(r["verdict"] == v for r in runs.values()) for v in ("dong_y", "khac", "none")}
    print(f"Tổng {len(runs)} câu: đồng ý {counts['dong_y']}, chọn khác {counts['khac']}, NONE {counts['none']}.")
    print(f"Token: vào {sum(r['prompt_tokens'] for r in runs.values())}, ra {sum(r['completion_tokens'] for r in runs.values())}. "
          f"Chi phí theo LiteLLM: {sum(r['cost_usd'] for r in runs.values()):.4f} USD (0 nghĩa là LiteLLM chưa có bảng giá model).")

    flagged = [
        {"question_id": r["question_id"], "ket_qua": r["verdict"], "judge_chon": r["choice"], "dap_an_luu": r["answer"],
         "cau_hoi": by_id[r["question_id"]]["stem"], **by_id[r["question_id"]]["options"], "ly_do_judge": r["reason"]}
        for r in runs.values() if r["verdict"] != "dong_y"
    ]
    path = RESULTS_DIR / "judge_nghi_ngo.csv"
    fields = ["question_id", "ket_qua", "judge_chon", "dap_an_luu", "cau_hoi", "A", "B", "C", "D", "ly_do_judge"]
    write_csv(path, flagged, fields)
    print(f"Câu cần người xem lại: {len(flagged)} → {path}")


if __name__ == "__main__":
    main()
