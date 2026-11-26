"""Xuất ngân hàng câu hỏi môn NLP từ DB thành JSONL cho giai đoạn 2 (đọc được bằng prepare_data.py --bank).

Mỗi dòng: {id, group, context, question, choices, correctchoice, questiontype, reviewed}
  group    = "doc<document_id>" — prepare_data chia train/dev/test theo bài học, không theo câu
  context  = nội dung các chunk nguồn của câu hỏi (embed_text)
  reviewed = câu đã được 2 người chấm duyệt đạt cả 4 tiêu chí (eval/mcq/data/phieu_chot.csv)

Chỉ lấy câu accepted của tài liệu còn hoạt động, do pipeline v1 sinh (pipeline v2 sinh ra sau sẽ không lẫn vào).
Chạy trong container API (cần DATABASE_URL):
  python -m training.export_bank --out training/data/raw/bank.jsonl [--approved-only]
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.generation.common import LETTERS
from app.models import Chunk, Document, Question

EVAL_DATA = Path("eval/mcq/data")


def approved_ids() -> set[int] | None:
    """question_id đã được duyệt đạt; None nếu chưa có phiếu chốt."""
    final, key = EVAL_DATA / "phieu_chot.csv", EVAL_DATA / "khoa_mau.csv"
    if not (final.exists() and key.exists()):
        return None
    from eval.mcq.common import read_csv
    from eval.mcq.step4_agreement import parse_final

    verdicts = parse_final(read_csv(final))
    if verdicts is None:
        return None
    code_to_qid = {r["ma_cau"]: int(r["question_id"]) for r in read_csv(key)}
    return {code_to_qid[c] for c, ok in verdicts.items() if ok and c in code_to_qid}


def review_verdicts() -> dict[int, bool] | None:
    """question_id → đạt/không đạt, cho các câu đã được người chấm. Ưu tiên phiếu chốt của 2 người;
    nếu chỉ có phiếu người 1 thì dùng phiếu đó (đạt = cả 4 tiêu chí đều bằng 1)."""
    from eval.mcq.common import BINARY_CRITERIA, read_csv

    key_path, sheet1 = EVAL_DATA / "khoa_mau.csv", EVAL_DATA / "phieu_cham_nguoi1.csv"
    if not key_path.exists():
        return None
    code_to_qid = {r["ma_cau"]: int(r["question_id"]) for r in read_csv(key_path)}
    final = EVAL_DATA / "phieu_chot.csv"
    if final.exists():
        from eval.mcq.step4_agreement import parse_final

        verdicts = parse_final(read_csv(final))
        if verdicts is not None:
            return {code_to_qid[c]: ok for c, ok in verdicts.items() if c in code_to_qid}
    if sheet1.exists() and not (EVAL_DATA / "phieu_cham_nguoi2.csv").exists():
        out = {}
        for r in read_csv(sheet1):
            vals = [(r.get(c) or "").strip() for c in BINARY_CRITERIA]
            if all(v in ("0", "1") for v in vals) and r["ma_cau"] in code_to_qid:
                out[code_to_qid[r["ma_cau"]]] = all(v == "1" for v in vals)
        return out or None
    return None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="training/data/raw/bank.jsonl")
    ap.add_argument("--approved-only", action="store_true", help="chỉ xuất câu đã được người chấm duyệt đạt")
    ap.add_argument("--drop-failed", action="store_true",
                    help="bỏ các câu người chấm đã chấm KHÔNG đạt; câu chưa chấm vẫn giữ")
    ap.add_argument("--docs", nargs="+", type=int, help="chỉ lấy các tài liệu có id này")
    args = ap.parse_args(argv)

    verdicts = review_verdicts()
    approved = None if verdicts is None else {i for i, ok in verdicts.items() if ok}
    failed = set() if verdicts is None else {i for i, ok in verdicts.items() if not ok}
    if (args.approved_only or args.drop_failed) and verdicts is None:
        raise SystemExit("Chưa có phiếu chấm (eval/mcq/data/phieu_cham_nguoi1.csv + khoa_mau.csv).")

    rows = []
    with SessionLocal() as db:
        stmt = (select(Question).join(Document, Document.id == Question.document_id)
                .where(Question.status == "accepted", Document.is_active))
        if args.docs:
            stmt = stmt.where(Question.document_id.in_(args.docs))
        questions = list(db.scalars(stmt))
        chunk_ids = {i for q in questions for i in q.source_chunk_ids}
        chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))} if chunk_ids else {}
    for q in questions:
        if (q.pipeline_version or "v1") != "v1":
            continue
        reviewed = approved is not None and q.id in approved
        if args.approved_only and not reviewed:
            continue
        if args.drop_failed and q.id in failed:
            continue
        letters = [k for k in LETTERS if k in q.options]
        context = "\n".join(chunks[i].embed_text for i in q.source_chunk_ids if i in chunks)
        rows.append({"id": q.id, "group": f"doc{q.document_id}", "context": context, "question": q.stem,
                     "choices": [q.options[k] for k in letters], "correctchoice": letters.index(q.answer),
                     "questiontype": q.bloom_level or "", "reviewed": reviewed})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Đã xuất {len(rows)} câu ({sum(r['reviewed'] for r in rows)} câu đã duyệt đạt, "
          f"{len(failed & {r['id'] for r in rows})} câu chấm không đạt còn giữ) → {out}")
    from collections import Counter
    print("Số câu theo bài:", dict(sorted(Counter(r["group"] for r in rows).items())))
    if approved is None:
        print("Lưu ý: chưa có phiếu chấm chốt, nên chưa câu nào được đánh dấu reviewed.")


if __name__ == "__main__":
    main()
