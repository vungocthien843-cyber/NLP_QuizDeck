"""Chuẩn bị thử nghiệm sinh viên (Mốc 3, G4/G5). Chạy SAU G1 và scripts\\_da_chay\\2_chon_lai_v3.bat, trong container API.

1. Chọn N slide (mặc định 15) có cả câu V1 (C0) và câu V3 (C5) đạt trong kết quả G1, ưu tiên slide mà ngân hàng có
   sẵn câu hỏi (để bước luyện tập có câu nhắm đúng ý đó), rải đều theo bài.
2. Nhập 2N câu vào DB với status = 'experiment' (không lọt vào đề ngẫu nhiên / luyện tập), đủ option_meta:
   V3 lấy nhãn hiểu nhầm của pipeline; V1 gắn nhãn bằng một lần gọi LLM mỗi câu (cùng prompt B2, ~0,01 USD tổng).
   Mức khó ước lượng theo ngưỡng của ngân hàng (không đổi mức của câu ngân hàng).
3. Tạo 2 đề cố định, đối trọng (counterbalanced): mỗi slide có mặt ở CẢ HAI đề, nửa số slide V1 ở Đề 1 và V3 ở Đề 2,
   nửa còn lại ngược lại → mỗi đề trộn V1/V3 50/50, thứ tự đề không trùng với phiên bản.
4. Tạo danh sách mã sinh viên, chia ngẫu nhiên cân bằng 2 nhóm: A luyện điểm yếu, B luyện đề thường (đối chứng).
5. Ghi data/thu_nghiem.json (API đọc file này để mở thử nghiệm trong giao diện), de_thu_nghiem.csv, danh_sach_ma.csv,
   phat_ma_sinh_vien.csv.

  python -m eval.student.chuan_bi                          # 15 slide, 20 mã sv01..sv20, luyện tập 10 câu
  python -m eval.student.chuan_bi --codes ma_lop.txt       # dùng mã sinh viên thật (mỗi dòng một mã)
  python -m eval.student.chuan_bi --dry-run                # chỉ in kế hoạch, không ghi DB
  python -m eval.student.chuan_bi --close                  # đóng thử nghiệm (đổi tên thu_nghiem.json), giữ dữ liệu
"""
import argparse
import asyncio
import json
import random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from eval.student.common import CODES, DATA, ITEMS, ROSTER, write_csv

LETTERS = "ABCD"
NAME = "G4"


def read_results(results: Path, cfg: str) -> dict[int, tuple[dict, dict]]:
    p = results / f"questions_{cfg}.jsonl"
    if not p.exists():
        raise SystemExit(f"Không thấy {p}. Đã chạy G1 xong chưa?")
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("question") and r["meta"].get("passed"):
                out[r["meta"]["seed_chunk"]] = (r["question"], r["meta"])
    return out


def choose_chunks(common: list[int], chunk_doc: dict[int, int], coverage: dict[int, int], n: int,
                  rng: random.Random) -> list[int]:
    """Ưu tiên slide có câu trong ngân hàng; rải đều theo bài (lần lượt mỗi bài một slide)."""
    by_doc = defaultdict(list)
    for c in common:
        by_doc[chunk_doc.get(c)].append(c)
    for g in by_doc.values():
        rng.shuffle(g)
        g.sort(key=lambda c: coverage.get(c, 0) > 0)          # có ngân hàng xếp cuối → pop() lấy trước
    out = []
    while len(out) < n and any(by_doc.values()):
        for d in sorted(by_doc, key=str):
            if by_doc[d] and len(out) < n:
                out.append(by_doc[d].pop())
    return out


def build_question(q: dict, meta: dict, version: str, doc_id: int, rng: random.Random):
    from app.models import Question

    seed = meta["seed_chunk"]
    texts = [q["answer"], *q["distractors"]]
    order = list(range(4))
    rng.shuffle(order)
    options = {LETTERS[i]: texts[j] for i, j in enumerate(order)}
    answer = LETTERS[order.index(0)]
    rat = q.get("rationales") or {}
    picked = {" ".join(p["text"].lower().split()): p for p in (meta.get("v2") or {}).get("picked") or []}
    option_meta = {}
    for letter, text in options.items():
        if letter == answer:
            option_meta[letter] = {"role": "key"}
        else:
            p = picked.get(" ".join(text.lower().split()), {})
            option_meta[letter] = {"role": "distractor", "source": p.get("source", "v1"),
                                   "error_type": p.get("error_type"), "candidate_id": None}
    others = [c for c in (q.get("source_chunk_ids") or []) if c != seed]
    v2 = meta.get("v2") or {}
    return Question(
        document_id=doc_id, stem=q["stem"], options=options, answer=answer,
        rationales={k: rat.get(v, "") for k, v in options.items()},
        explanation=q.get("explanation") or f"Căn cứ trên slide: “{q.get('evidence', '')}”",
        bloom_level=meta.get("bloom"), source_chunk_ids=[seed, *others], status="experiment",
        validation={"evidence_text": q.get("evidence"), "key_point": q.get("key_point"),
                    "experiment": {"name": NAME, "version": version, "seed_chunk": seed}},
        pipeline_version="v1" if version == "V1" else "v2", answer_type=v2.get("answer_type"),
        selection=dict(v2.get("selection") or {}), option_meta=option_meta,
        concept=q.get("key_point") or q["stem"],
    )


async def tag_v1(items: list[tuple]) -> int:
    """Gắn loại hiểu nhầm cho đáp án nhiễu của câu V1 (V3 đã có nhãn từ pipeline). Trả số câu gắn được."""
    from app.generation.candidates import Candidate, tag_misconceptions

    async def one(qobj, q):
        letters = [k for k, m in qobj.option_meta.items() if m["role"] == "distractor"]
        cands = [Candidate(text=qobj.options[k], source="v1") for k in letters]
        res = await tag_misconceptions(q.get("context") or "", q["stem"], q["answer"], q.get("key_point") or "", cands)
        if res.get("tagged"):
            qobj.option_meta = {**qobj.option_meta, **{k: {**qobj.option_meta[k], "error_type": c.error_type}
                                                       for k, c in zip(letters, cands, strict=True)}}
            return 1
        return 0
    sem = asyncio.Semaphore(4)

    async def guarded(a):
        async with sem:
            return await one(*a)
    return sum(await asyncio.gather(*(guarded(a) for a in items)))


def make_roster(codes: list[str], rng: random.Random) -> dict[str, str]:
    groups = ["A", "B"] * (len(codes) // 2 + 1)
    groups = groups[:len(codes)]
    rng.shuffle(groups)
    return dict(zip(codes, groups, strict=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="eval/v2/results/G1")
    ap.add_argument("--n", type=int, default=15, help="số câu mỗi đề (= số slide)")
    ap.add_argument("--students", type=int, default=20, help="số mã tạo sẵn sv01.. (bỏ qua nếu có --codes)")
    ap.add_argument("--codes", help="file mã sinh viên thật, mỗi dòng một mã")
    ap.add_argument("--practice-n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--no-tag", action="store_true", help="không gọi LLM gắn nhãn câu V1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="tạo lại dù đã có thử nghiệm (thử nghiệm cũ bị đóng)")
    ap.add_argument("--close", action="store_true")
    a = ap.parse_args()

    from app.experiment import config_path
    cfg_path = config_path()
    if a.close:
        if cfg_path.exists():
            dst = cfg_path.with_name(f"thu_nghiem_dong_{datetime.now():%Y%m%d-%H%M%S}.json")
            cfg_path.rename(dst)
            print(f"Đã đóng thử nghiệm (cấu hình chuyển sang {dst.name}); dữ liệu làm bài vẫn giữ trong DB.")
        else:
            print("Không có thử nghiệm nào đang mở.")
        return
    if cfg_path.exists() and not a.force and not a.dry_run:
        raise SystemExit(f"Đã có thử nghiệm đang mở ({cfg_path}). Thêm --force để tạo lại, hoặc --close để đóng.")

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.learner.difficulty import level_like_bank
    from app.models import Chunk, Question, Quiz, QuizQuestion

    rng = random.Random(a.seed)
    v1, v3 = read_results(Path(a.results), "C0"), read_results(Path(a.results), "C5")
    common = sorted(set(v1) & set(v3))
    with SessionLocal() as db:
        chunk_doc = dict(db.execute(select(Chunk.id, Chunk.document_id).where(Chunk.id.in_(common))).all())
        wanted = set(common)
        coverage = Counter(ids[0] for ids in db.scalars(select(Question.source_chunk_ids)
                                                         .where(Question.status == "accepted"))
                           if ids and ids[0] in wanted)
    common = [c for c in common if c in chunk_doc]
    if len(common) < a.n:
        raise SystemExit(f"Chỉ có {len(common)} slide có cả câu V1 và V3 đạt, cần {a.n}. Giảm --n.")
    chunks = choose_chunks(common, chunk_doc, coverage, a.n, rng)
    half = (len(chunks) + 1) // 2
    plan = [(c, "V1", "V3") for c in chunks[:half]] + [(c, "V3", "V1") for c in chunks[half:]]  # (slide, đề 1, đề 2)
    codes = ([x.strip().lower() for x in Path(a.codes).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
             if a.codes else [f"sv{i:02d}" for i in range(1, a.students + 1)])
    if len(set(codes)) != len(codes):
        raise SystemExit("Danh sách mã có mã trùng.")
    roster = make_roster(codes, rng)
    print(f"Slide chọn: {len(chunks)} ({sum(coverage.get(c, 0) > 0 for c in chunks)} slide có câu trong ngân hàng "
          "để luyện tập)")
    print(f"Mã: {len(codes)} (nhóm A {sum(g == 'A' for g in roster.values())}, "
          f"nhóm B {sum(g == 'B' for g in roster.values())})")
    if a.dry_run:
        for c, d1, d2 in plan:
            print(f"  slide {c} (bài {chunk_doc[c]}, {coverage.get(c, 0)} câu ngân hàng): Đề 1 = {d1}, Đề 2 = {d2}")
        return

    with SessionLocal() as db:
        built = {}          # (slide, phiên bản) → Question
        for c, _, _ in plan:
            for ver, src in (("V1", v1), ("V3", v3)):
                built[(c, ver)] = build_question(*src[c], ver, chunk_doc[c], rng)
        db.add_all(built.values())
        db.flush()
        if not a.no_tag:
            todo = [(built[(c, "V1")], v1[c][0]) for c, _, _ in plan]
            n = asyncio.run(tag_v1(todo))
            print(f"Gắn nhãn hiểu nhầm cho câu V1: {n}/{len(todo)} câu")
        counts = level_like_bank(db, list(built.values()))
        print(f"Mức khó ước lượng của {len(built)} câu: {counts}")
        quizzes = {}
        for k in (1, 2):
            qz = Quiz(scope={"experiment": NAME, "fixed": k}, num_questions=len(plan), mode="normal")
            db.add(qz)
            db.flush()
            quizzes[k] = qz
            items = [built[(c, d1 if k == 1 else d2)] for c, d1, d2 in plan]
            rng.shuffle(items)
            db.add_all(QuizQuestion(quiz_id=qz.id, question_id=q.id, position=i) for i, q in enumerate(items, 1))
        db.commit()
        rows = []
        for k, qz in quizzes.items():
            for qq in db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == qz.id).order_by(QuizQuestion.position)):
                q = db.get(Question, qq.question_id)
                exp = q.validation["experiment"]
                rows.append({"de": k, "quiz_id": qz.id, "vi_tri": qq.position, "question_id": q.id,
                             "phien_ban": exp["version"], "slide": exp["seed_chunk"], "document_id": q.document_id,
                             "muc_kho": q.difficulty_est, "bloom": q.bloom_level,
                             "co_nhan": sum(bool(m.get("error_type")) for m in q.option_meta.values())})
        doc_ids = sorted({chunk_doc[c] for c in chunks})
        cfg = {"name": NAME, "created_at": datetime.now().isoformat(timespec="seconds"),
               "scope": {"document_ids": doc_ids}, "quiz1_id": quizzes[1].id, "quiz2_id": quizzes[2].id,
               "practice_n": a.practice_n, "members": roster}
    DATA.mkdir(parents=True, exist_ok=True)
    write_csv(ITEMS, rows)
    write_csv(ROSTER, [{"ma": c, "nhom": g} for c, g in roster.items()])
    write_csv(CODES, [{"stt": i, "ma": c, "ho_ten": "", "ky_nhan": ""} for i, c in enumerate(codes, 1)])
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đề 1 = quiz {quizzes[1].id}, Đề 2 = quiz {quizzes[2].id}; phạm vi luyện tập: bài {doc_ids}")
    print(f"Đã mở thử nghiệm ({cfg_path}). Phát mã trong {CODES.name}; GIỮ RIÊNG {ROSTER.name} (có nhóm).")


if __name__ == "__main__":
    main()
