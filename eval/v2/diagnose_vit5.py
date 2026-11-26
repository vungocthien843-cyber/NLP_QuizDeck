"""Chẩn đoán nguồn ViT5 của pipeline v2 (kế hoạch v3, việc A1). KHÔNG ghi gì vào database.

Trả lời câu hỏi: ứng viên của ViT5 mất ở đâu?
  1. môi trường   checkpoint có trong container không, phiên bản transformers/torch, thiết bị
  2. nạp model    get_generator() có lỗi không (trong pipeline lỗi này bị nuốt, chỉ còn một dòng log)
  3. sinh         model trả về gì với các câu hỏi thật trong ngân hàng (diverse_beam và sampling)
  4. lọc          ứng viên bị loại ở bước nào: trùng (dedupe) | form | copy | nli | còn sống

Lấy câu hỏi đã accepted trong DB (ưu tiên câu v2 vì có evidence), dùng lại stem, đáp án đúng, chunk hạt giống.

Chạy trong container API:
  docker compose exec api python -m eval.v2.diagnose_vit5 --n 10
  docker compose exec api python -m eval.v2.diagnose_vit5 --n 10 --docs 17 22 --decoding diverse_beam sampling
Kết quả: in bảng tóm tắt ra màn hình, chi tiết từng câu ở eval/v2/results/diagnose_vit5_<thời điểm>.json
"""
import argparse
import json
import platform
import random
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.models import Chunk, Question

RESULTS = Path(__file__).parent / "results"
STAGES = ("dedupe", "form", "copy", "nli", "alive")


def environment() -> dict:
    cfg = get_config().distractor
    ckpt = Path(cfg.vit5_checkpoint)
    env = {
        "python": platform.python_version(),
        "checkpoint": str(ckpt),
        "checkpoint_abs": str(ckpt.resolve()),
        "checkpoint_files": sorted(p.name for p in ckpt.iterdir()) if ckpt.is_dir() else "KHÔNG CÓ THƯ MỤC",
        "sources": cfg.sources,
        "decoding_cfg": cfg.decoding,
        "device_cfg": cfg.device,
    }
    for mod in ("torch", "transformers", "tokenizers", "sentencepiece"):
        try:
            env[mod] = __import__(mod).__version__
        except Exception as exc:  # noqa: BLE001
            env[mod] = f"LỖI: {exc}"
    try:
        import torch
        env["cuda"] = torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        env["cuda"] = None
    from app.local_models import vit5_available
    env["vit5_available"] = vit5_available()
    return env


def sample_questions(n: int, docs: list[int] | None, seed: int) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Question).where(Question.status == "accepted")
        if docs:
            stmt = stmt.where(Question.document_id.in_(docs))
        qs = list(db.scalars(stmt))
        qs.sort(key=lambda q: (q.pipeline_version != "v2", q.id))      # câu v2 trước (có evidence chuẩn)
        v2 = [q for q in qs if q.pipeline_version == "v2"]
        pool = v2 if len(v2) >= n else qs
        rng = random.Random(seed)
        picked = rng.sample(pool, min(n, len(pool)))
        chunk_ids = {q.source_chunk_ids[0] for q in picked}
        chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))}
    out = []
    for q in picked:
        chunk = chunks.get(q.source_chunk_ids[0])
        if not chunk:
            continue
        v = q.validation or {}
        out.append({"question_id": q.id, "pipeline": q.pipeline_version, "stem": q.stem,
                    "answer": q.options[q.answer], "evidence": v.get("evidence_text") or "",
                    "context": chunk.embed_text})
    return out


def run_one(gen, item: dict, decoding: str, n: int) -> dict:
    from app.generation import filters
    from app.generation.candidates import Candidate, dedupe

    t0 = time.perf_counter()
    raw = gen.generate(item["stem"], item["answer"], item["context"], n, decoding)
    gen_s = time.perf_counter() - t0
    kept = dedupe(raw, item["answer"])
    keep_n = get_config().distractor.max_vit5_keep
    cands = [Candidate(t, "vit5") for t in kept[:keep_n]]
    filters.apply_rule_filters(cands, item["answer"])
    premise = filters.nli_premise(item["evidence"] or item["answer"], item["context"], item["stem"], item["answer"])
    key_entail, nli_mode = filters.apply_nli_filter(cands, item["stem"], item["answer"], premise)
    stages = Counter({"dedupe": len(raw) - len(cands)})
    stages.update(c.rejected_at or "alive" for c in cands)
    return {
        "decoding": decoding, "seconds": round(gen_s, 2), "raw": raw,
        "candidates": [c.as_dict() for c in cands], "stages": dict(stages),
        "key_entail": key_entail, "nli_mode": nli_mode,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10, help="số câu hỏi lấy từ ngân hàng")
    ap.add_argument("--docs", nargs="*", type=int, help="chỉ lấy câu của các bài này")
    ap.add_argument("--decoding", nargs="+", default=["diverse_beam", "sampling"],
                    choices=["diverse_beam", "beam", "sampling"])
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / f"diagnose_vit5_{datetime.now():%Y%m%d-%H%M%S}.json"
    report: dict = {"env": environment()}
    print("== 1. Môi trường ==")
    for k, v in report["env"].items():
        print(f"  {k}: {v}")

    print("\n== 2. Nạp model ==")
    try:
        from app.local_models import get_generator
        t0 = time.perf_counter()
        gen = get_generator()
        report["load"] = {"ok": True, "seconds": round(time.perf_counter() - t0, 1), "device": gen.device}
        print(f"  OK sau {report['load']['seconds']} s, thiết bị {gen.device}")
    except Exception as exc:  # noqa: BLE001
        report["load"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
        print(f"  LỖI NẠP MODEL: {report['load']['error']}")
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nChi tiết: {out_path}")
        return

    items = sample_questions(a.n, a.docs, a.seed)
    print(f"\n== 3–4. Sinh và lọc trên {len(items)} câu hỏi ==")
    n_cand = get_config().distractor.n_candidates
    report["items"] = []
    totals = {d: Counter() for d in a.decoding}
    secs = {d: [] for d in a.decoding}
    errors = Counter()
    for item in items:
        row = {**{k: item[k] for k in ("question_id", "pipeline", "stem", "answer")}, "runs": []}
        for dec in a.decoding:
            try:
                r = run_one(gen, item, dec, n_cand)
                totals[dec].update(r["stages"])
                secs[dec].append(r["seconds"])
            except Exception as exc:  # noqa: BLE001
                r = {"decoding": dec, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
                errors[f"{dec}: {type(exc).__name__}"] += 1
            row["runs"].append(r)
        report["items"].append(row)
        first = row["runs"][0]
        print(f"\n  [q{item['question_id']}] {item['stem'][:90]}")
        print(f"    đáp án đúng: {item['answer'][:90]}")
        if "error" in first:
            print(f"    LỖI ({first['decoding']}): {first['error']}")
        else:
            for c in first["candidates"]:
                print(f"    - [{c['rejected_at'] or 'SỐNG'}] copy={c['copy_score']} nli={c['entail_prob']} :: {c['text'][:90]}")

    print("\n== Tóm tắt: ứng viên dừng ở bước nào (tổng trên mọi câu) ==")
    print("  decoding       " + "  ".join(f"{s:>7}" for s in STAGES) + "   s/câu")
    for dec in a.decoding:
        t = totals[dec]
        avg = sum(secs[dec]) / len(secs[dec]) if secs[dec] else 0
        print(f"  {dec:<14} " + "  ".join(f"{t.get(s, 0):>7}" for s in STAGES) + f"   {avg:5.1f}")
    if errors:
        print(f"  Lỗi khi sinh: {dict(errors)}")
    report["summary"] = {d: dict(totals[d]) for d in a.decoding}
    report["errors"] = dict(errors)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nChi tiết từng câu: {out_path}")


if __name__ == "__main__":
    main()
