"""Bước 3: tạo phiếu chấm cho 2 người. Mẫu phân tầng, thứ tự ngẫu nhiên, seed cố định.

Phiếu không có trạng thái accepted / rejected để người chấm không biết kết quả lọc.
Chạy: python -m eval.mcq.step3_sample [--accepted 40] [--rejected 20] [--pilot 10] [--seed 42] [--force]
"""
import argparse
import random
from collections import Counter

from app.generation.common import allocate
from eval.mcq.common import (
    BINARY_CRITERIA,
    DEFAULT_SEED,
    SAMPLE_KEY,
    SCALE_CRITERIA,
    SHEET_PILOT,
    SHEET_RATER1,
    SHEET_RATER2,
    fail,
    load_chunks,
    load_questions,
    rule_of,
    write_csv,
)


def sample_accepted(questions: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Giữ đúng tỉ lệ các mức Bloom của câu accepted."""
    n = min(n, len(questions))
    counts = Counter(q["bloom_level"] for q in questions)
    picked: list[dict] = []
    for level, quota in allocate(n, dict(counts)).items():
        picked += rng.sample([q for q in questions if q["bloom_level"] == level], quota)
    return picked


def sample_rejected(questions: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Rải đều theo luật loại: lần lượt lấy mỗi luật một câu để luật hiếm vẫn có mặt."""
    by_rule: dict[str, list[dict]] = {}
    for q in questions:
        by_rule.setdefault(rule_of(q["validation"]) or "khong_ro", []).append(q)
    for group in by_rule.values():
        rng.shuffle(group)
    picked: list[dict] = []
    while len(picked) < n and any(by_rule.values()):
        for rule in sorted(by_rule):
            if by_rule[rule] and len(picked) < n:
                picked.append(by_rule[rule].pop())
    return picked


def to_sheet_row(code: str, q: dict, chunks: dict[int, dict]) -> dict:
    sources = [chunks[i] for i in q["source_chunk_ids"] if i in chunks]
    row = {
        "ma_cau": code,
        "muc_bloom": q["bloom_level"],
        "cau_hoi": q["stem"],
        **{letter: q["options"][letter] for letter in "ABCD"},
        "dap_an": q["answer"],
        "giai_thich": q["explanation"] or "",
        "evidence": q["validation"].get("evidence_text") or "",
        "noi_dung_slide": "\n\n".join(c["embed_text"] for c in sources),
    }
    row.update({criterion: "" for criterion in (*BINARY_CRITERIA, *SCALE_CRITERIA)})
    row["ghi_chu"] = ""
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", type=int, default=40)
    parser.add_argument("--rejected", type=int, default=20)
    parser.add_argument("--pilot", type=int, default=10, help="Số câu chấm thử chung, không tính vào kết quả")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--force", action="store_true", help="Ghi đè phiếu cũ, MẤT mọi điểm đã chấm")
    args = parser.parse_args()
    if not args.force and any(p.exists() for p in (SHEET_RATER1, SHEET_RATER2, SAMPLE_KEY)):
        fail("phiếu chấm đã có. Tạo lại sẽ xoá điểm đã chấm; thêm --force nếu chắc chắn.")

    questions = sorted(load_questions(), key=lambda q: q["id"])
    chunks = load_chunks()
    rng = random.Random(args.seed)
    accepted = [q for q in questions if q["status"] == "accepted"]
    rejected = [q for q in questions if q["status"] == "rejected"]

    pilot = rng.sample(accepted, min(args.pilot, len(accepted)))
    pilot_ids = {q["id"] for q in pilot}
    main_accepted = sample_accepted([q for q in accepted if q["id"] not in pilot_ids], args.accepted, rng)
    main_rejected = sample_rejected(rejected, args.rejected, rng)
    sample = main_accepted + main_rejected
    rng.shuffle(sample)

    codes = {q["id"]: f"C{i:03d}" for i, q in enumerate(sample, 1)}
    rows = [to_sheet_row(codes[q["id"]], q, chunks) for q in sample]
    write_csv(SHEET_RATER1, rows)
    write_csv(SHEET_RATER2, rows)
    write_csv(SHEET_PILOT, [to_sheet_row(f"T{i:02d}", q, chunks) for i, q in enumerate(pilot, 1)])
    write_csv(SAMPLE_KEY, [{"ma_cau": codes[q["id"]], "question_id": q["id"], "status": q["status"],
                            "rule": rule_of(q["validation"]) or "", "bloom_level": q["bloom_level"]} for q in sample])

    print(f"Mẫu chính: {len(sample)} câu ({len(main_accepted)} accepted, {len(main_rejected)} rejected)")
    if len(main_rejected) < args.rejected:
        print(f"Lưu ý: chỉ có {len(rejected)} câu rejected, thấp hơn mức {args.rejected}, nên đã lấy tất cả.")
    if len(main_accepted) < args.accepted:
        print(f"Lưu ý: chỉ còn {len(main_accepted)} câu accepted sau khi trừ phần chấm thử.")
    print(f"Chấm thử: {len(pilot)} câu → {SHEET_PILOT.name}")
    print(f"Phiếu: {SHEET_RATER1.name}, {SHEET_RATER2.name}")


if __name__ == "__main__":
    main()
