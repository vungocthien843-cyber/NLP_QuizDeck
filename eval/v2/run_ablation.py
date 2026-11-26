"""Bảng so sánh cấu hình của phiên bản 2 (docs/ke-hoach-v2.md, mục 9). KHÔNG ghi gì vào ngân hàng câu hỏi.

Cấu hình (sinh trên CÙNG một bộ hạt giống, cố định bằng --seed):
  C0  v1: một lần gọi LLM viết cả câu
  C1  v2, ứng viên chỉ từ LLM
  C2  v2, ứng viên chỉ từ ViT5 giai đoạn 1
  (C3 – ViT5 giai đoạn 2 – không thực hiện)
  C4  v2, ViT5 giai đoạn 1 + LLM (đầy đủ)
  C5  v3: C4 + gắn nhãn hiểu nhầm, ràng buộc đa dạng loại lỗi, khái niệm lân cận, 5 ứng viên LLM + sinh bù
Trên tập ứng viên của C4 còn so 4 cách chọn bộ 3: top3 | random | entropy_no_delta (bài gốc) | entropy (có δ).

Chỉ số tự động — model giải độc lập (models.judge_independent), mỗi điều kiện chạy --runs lần, xáo phương án:
  open_book_correct    có ngữ cảnh mà chọn đúng          → phải gần 100%
  closed_book_correct  không ngữ cảnh mà chọn đúng      → càng thấp đáp án nhiễu càng đánh lừa tốt
  options_only_correct chỉ xem 4 phương án, không stem   → gần 25%; cao hơn là đáp án lộ qua hình thức
  copy_rate            phương án sai chép đáp án đúng (> 0,95, K5)
  llm_calls, cost_usd, seconds  chi phí cho mỗi câu
Kèm phiếu chấm người (từng đáp án nhiễu, trộn cấu hình, ẩn nhãn) để dùng lại quy trình eval/mcq.

Chạy (trong container API, đã có checkpoint ViT5):
  python -m eval.v2.run_ablation --docs 17 22 --n-seeds 100 --configs C0 C1 C2 C4 --runs 3
Kết quả: eval/v2/results/<thời điểm>/
"""
import argparse
import asyncio
import contextlib
import contextvars
import json
import random
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.generation import bank_builder as bb
from app.generation import filters, pipeline_v2, selector
from app.generation.common import LETTERS, format_context
from app.generation.filters import key_recall
from app.generation.validator import validate
from app.llm_client import JSON_MODE, acomplete, parse_json
from app.models import Chunk, Document
from eval.mcq.common import wilson, write_csv

RESULTS = Path(__file__).parent / "results"
# Các cấu hình v2 (C1–C4) TẮT tường minh mọi tính năng v3, để bảng so sánh không đổi khi config.yaml bật v3.
V2_ONLY = {"distractor.tag_errors": False, "distractor.min_error_types": 0, "distractor.neighbor_concepts": 0,
           "distractor.min_alive": 0}
CONFIGS = {
    "C0": {"bank.pipeline": "v1"},
    "C1": {"bank.pipeline": "v2", "distractor.sources": ["llm"], "distractor.llm_candidates": 8, **V2_ONLY},
    "C2": {"bank.pipeline": "v2", "distractor.sources": ["vit5"],
           "distractor.vit5_checkpoint": "checkpoints/dg-vit5-stage1/best", **V2_ONLY},
    # Giai đoạn 2 không dùng (kế hoạch điều chỉnh ngày 06/11): C3 bỏ, C4 dùng ViT5 giai đoạn 1
    "C4": {"bank.pipeline": "v2", "distractor.sources": ["vit5", "llm"], "distractor.llm_candidates": 3,
           "distractor.vit5_checkpoint": "checkpoints/dg-vit5-stage1/best", **V2_ONLY},
    # v3 (docs/ke-hoach-v3.md): C4 + 5 ứng viên LLM, sinh bù khi < 5, khái niệm lân cận, gắn nhãn hiểu nhầm,
    # ràng buộc ≥ 2 loại lỗi. Nguồn ViT5 theo config.yaml (giữ hay tắt tuỳ kết quả A2).
    "C5": {"bank.pipeline": "v2", "distractor.llm_candidates": 5, "distractor.min_alive": 5,
           "distractor.neighbor_concepts": 3, "distractor.tag_errors": True, "distractor.min_error_types": 2},
}
SELECTION_MODES = ("top3", "random", "entropy_no_delta", "entropy")

# ---------- Ghi lại bộ lọc NLI (để hiệu chỉnh ngưỡng; không đổi hành vi của pipeline) ----------
_NLI_LOG: contextvars.ContextVar = contextvars.ContextVar("nli_log", default=None)
_orig_nli_filter = filters.apply_nli_filter


def _logged_nli_filter(cands, stem, answer, premise):
    out = _orig_nli_filter(cands, stem, answer, premise)
    key_entail, mode = out if isinstance(out, tuple) else (out, None)
    log = _NLI_LOG.get()
    if log is not None:
        log.append({"stem": stem, "answer": answer, "premise": premise, "key_entail": key_entail, "mode": mode})
    return out


filters.apply_nli_filter = _logged_nli_filter   # pipeline_v2 gọi qua filters.apply_nli_filter


class _WarningsToMeta(__import__("logging").Handler):
    """Ghi WARNING/ERROR phát ra trong lúc sinh một câu vào meta["warnings"] của câu đó (trước đây chỉ in ra
    terminal, mất khi đóng cửa sổ; ví dụ 'Nguồn vit5 lỗi')."""
    def emit(self, record):
        log = _WARN_LOG.get()
        if log is not None and record.levelno >= 30:
            log.append(f"{record.name}: {record.getMessage()}"[:500])


_WARN_LOG: contextvars.ContextVar = contextvars.ContextVar("warn_log", default=None)
__import__("logging").getLogger().addHandler(_WarningsToMeta())


def _compact_pool(pool: list[dict]) -> list[dict]:
    keep = ("text", "source", "rejected_at", "copy_score", "entail_prob", "score", "error_type", "error_type_self")
    return [{k: c.get(k) for k in keep} for c in pool]


_GEN_CKPT: dict = {}   # checkpoint ViT5 đang được cache


@contextlib.contextmanager
def override(cfg_overrides: dict):
    """Đổi tạm cấu hình trong bộ nhớ (get_config() được cache), trả lại như cũ khi xong."""
    import app.local_models as lm

    def reset_generator() -> None:      # chỉ nạp lại ViT5 khi checkpoint đổi (nạp lại thừa dễ gây tranh chấp)
        cur = get_config().distractor.vit5_checkpoint
        if _GEN_CKPT.setdefault("ckpt", cur) != cur:
            getattr(lm.get_generator, "cache_clear", lambda: None)()
            _GEN_CKPT["ckpt"] = cur

    cfg, old = get_config(), {}
    _GEN_CKPT.setdefault("ckpt", cfg.distractor.vit5_checkpoint)
    for path, value in cfg_overrides.items():
        section, key = path.split(".")
        obj = getattr(cfg, section)
        old[path] = getattr(obj, key)
        setattr(obj, key, value)
    reset_generator()
    try:
        yield
    finally:
        for path, value in old.items():
            section, key = path.split(".")
            setattr(getattr(cfg, section), key, value)
        reset_generator()


def pick_seeds(doc_ids: list[int], n: int, seed: int) -> list:
    with SessionLocal() as db:
        chunks = list(db.scalars(select(Chunk).join(Document, Document.id == Chunk.document_id).where(
            Chunk.document_id.in_(doc_ids), Chunk.is_active, Document.is_active).order_by(Chunk.document_id, Chunk.slide_no)))
    if not chunks:
        raise SystemExit("Không có chunk nào trong các bài đã chọn (--docs).")
    seeds = bb.select_seeds(chunks, n, rng=random.Random(seed))
    return seeds[:n]


def resolve_docs(pattern: str) -> list[int]:
    """Các bài đang dùng có tên file chứa pattern (không phân biệt hoa thường), ví dụ "Chuong" = 9 chương NLP."""
    with SessionLocal() as db:
        docs = list(db.scalars(select(Document).where(Document.is_active, Document.filename.ilike(f"%{pattern}%"))
                               .order_by(Document.filename)))
    if not docs:
        raise SystemExit(f"Không có bài nào có tên chứa '{pattern}'. Kiểm tra các bài đã nạp ở giao diện.")
    for d in docs:
        print(f"  bài {d.id}: {d.filename}")
    return [d.id for d in docs]


def pick_seeds_balanced(doc_ids: list[int], per_doc: int, seed: int) -> list:
    """Chia ĐỀU số hạt giống cho từng bài (sửa lỗi G1: pick_seeds cắt seeds[:n] sau khi rải theo thứ tự bài, nên
    bài có id lớn nhất gần như bị bỏ, ví dụ chương 9 chỉ được 2/100). Bỏ slide tiêu đề (slide 1) và slide hành chính
    (lộ trình, mục tiêu, tài liệu tham khảo, cảm ơn...). Trong mỗi bài, rải đều theo thứ tự slide; mức Bloom gán theo
    bank.bloom_mix trên toàn bộ hạt giống."""
    from app.generation.common import allocate, word_count
    from app.generation.pipeline_v2 import is_admin_slide

    cfg = get_config().bank
    rng = random.Random(seed)
    picked, report = [], []
    with SessionLocal() as db:
        for d in doc_ids:
            chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == d, Chunk.is_active)
                                     .order_by(Chunk.slide_no)))
            ok = [c for c in chunks if (c.slide_no or 0) > 1 and word_count(c) >= cfg.min_seed_words
                  and not is_admin_slide(c.embed_text or c.raw_text or "")]
            take = [ok[(i * len(ok)) // per_doc] for i in range(min(per_doc, len(ok)))]
            picked += take
            report.append(f"bài {d}: {len(take)}/{per_doc} hạt giống (đủ điều kiện {len(ok)}/{len(chunks)} slide)")
    levels = [lvl for lvl, cnt in allocate(len(picked), cfg.bloom_mix).items() for _ in range(cnt)]
    rng.shuffle(levels)
    print("\n".join(report))
    return [bb.Seed(chunk=c, bloom_level=lvl) for c, lvl in zip(picked, levels, strict=True)]


async def generate(seed_obj, context) -> tuple[dict | None, dict]:
    """Sinh một câu theo cấu hình hiện tại, chạy hậu kiểm của v1. Không lưu DB, không sinh lại."""
    t0 = time.perf_counter()
    meta: dict = {"seed_chunk": seed_obj.chunk.id, "bloom": seed_obj.bloom_level}
    nli_log: list = []
    _NLI_LOG.set(nli_log)
    meta["nli"] = nli_log
    warn_log: list = []
    _WARN_LOG.set(warn_log)
    meta["warnings"] = warn_log
    try:
        if get_config().bank.pipeline == "v2":
            mcq, v2 = await pipeline_v2.generate(seed_obj, context, [])
            meta.update(v2=v2)
        else:
            mcq = await bb.generate_one(seed_obj, context, [])
    except pipeline_v2.StepFailed as exc:
        details = {k: v for k, v in (exc.details or {}).items() if k != "pool"}
        pool = (exc.details or {}).get("pool") or []
        details["rejected_at"] = dict(__import__("collections").Counter(c.get("rejected_at") or "alive" for c in pool))
        details["pool"] = _compact_pool(pool)   # giữ ứng viên + entail_prob để hiệu chỉnh NLI
        meta.update(failed=exc.step, reason=exc.feedback, details=details, seconds=round(time.perf_counter() - t0, 2))
        return None, meta
    except Exception as exc:
        meta.update(failed=f"error: {exc}", seconds=round(time.perf_counter() - t0, 2))
        return None, meta
    result, report = validate(mcq, context, seed_obj.chunk.id)
    meta.update(passed=result.passed, reason=result.reason, seconds=round(time.perf_counter() - t0, 2))
    q = {"stem": mcq.stem, "answer": next(o.text for o in mcq.options if o.is_correct),
         "distractors": [o.text for o in mcq.options if not o.is_correct], "evidence": mcq.evidence,
         "context": format_context(context),
         # Mốc 3 (G4): đủ thông tin để nhập câu vào ngân hàng cho sinh viên làm (eval/student/nhap_cau.py)
         "key_point": mcq.key_point, "explanation": mcq.explanation, "source_chunk_ids": mcq.source_chunk_ids,
         "rationales": {o.text: o.rationale for o in mcq.options}}
    return q, meta


# ---------- Model giải ----------
SOLVER = {
    "open_book": "Đọc NGỮ CẢNH và trả lời câu hỏi trắc nghiệm. Chỉ dựa vào ngữ cảnh.\n\nNGỮ CẢNH:\n{context}\n\n"
                 "CÂU HỎI: {stem}\n{options}\n\nTrả về JSON {{\"choice\": \"A|B|C|D\"}}.",
    "closed_book": "Trả lời câu hỏi trắc nghiệm môn {course} bằng hiểu biết của bạn.\n\nCÂU HỎI: {stem}\n{options}\n\n"
                   "Trả về JSON {{\"choice\": \"A|B|C|D\"}}.",
    "options_only": "Dưới đây là 4 phương án của một câu trắc nghiệm, câu hỏi bị ẩn. Đoán phương án nào là đáp án đúng "
                    "chỉ dựa vào hình thức của các phương án.\n{options}\n\nTrả về JSON {{\"choice\": \"A|B|C|D\"}}.",
}


async def solve(q: dict, condition: str, rng: random.Random) -> bool | None:
    opts = [q["answer"], *q["distractors"]]
    order = list(range(len(opts)))
    rng.shuffle(order)
    listing = "\n".join(f"{LETTERS[i]}. {opts[j]}" for i, j in enumerate(order))
    prompt = SOLVER[condition].format(context=q["context"], stem=q["stem"], options=listing,
                                      course=get_config().course.name)
    try:
        res = await acomplete("judge_independent", [{"role": "user", "content": prompt}],
                              temperature=get_config().llm.temperature_judge, response_format=JSON_MODE)
        choice = str(parse_json(res.text).get("choice", "")).strip().upper()[:1]
    except Exception:
        return None
    return choice in LETTERS[:len(opts)] and order[LETTERS.index(choice)] == 0


async def solver_metrics(qs: list[dict], runs: int, seed: int) -> dict:
    sem = asyncio.Semaphore(get_config().bank.concurrency)
    out: dict = {}
    for cond in SOLVER:
        async def one(i: int, q: dict, r: int) -> bool | None:
            async with sem:
                return await solve(q, cond, random.Random(f"{seed}:{cond}:{i}:{r}"))
        res = [x for x in await asyncio.gather(*(one(i, q, r) for i, q in enumerate(qs) for r in range(runs)))
               if x is not None]
        lo, hi = wilson(sum(res), len(res))
        out[f"{cond}_correct"] = round(sum(res) / len(res), 4) if res else None
        out[f"{cond}_ci95"] = f"[{lo:.3f}, {hi:.3f}]"
    return out


FAIL_STEPS = ("key", "stem", "selection", "validator", "error")


def fail_breakdown(metas: list[dict]) -> dict:
    """Tỉ lệ hạt giống trượt ở từng bước (kế hoạch v3, việc A4). 'error' = lỗi gọi LLM / JSON hỏng."""
    n = max(len(metas), 1)
    steps = __import__("collections").Counter(
        "error" if str(m["failed"]).startswith("error") else m["failed"] for m in metas if m.get("failed"))
    steps["validator"] = sum(1 for m in metas if not m.get("failed") and m.get("passed") is False)
    return {f"fail_{s}": round(steps.get(s, 0) / n, 4) for s in FAIL_STEPS}


def timing_breakdown(metas: list[dict]) -> dict:
    """Thời gian trung bình (giây) của từng bước trên các câu sinh trọn vẹn (kế hoạch v3, việc A5)."""
    rows = [(m.get("v2") or {}).get("timing") for m in metas if m.get("v2")]
    rows = [r for r in rows if r]
    if not rows:
        return {}
    steps = sorted({k for r in rows for k in r})
    out = {f"t_{s}": round(sum(r.get(s, 0) for r in rows) / len(rows), 2) for s in steps}
    # chi tiết bên trong bước đáp án nhiễu: vit5 / llm (chạy song song) / nli / tag / score (reranker) / neighbors
    det = [((m.get("v2") or {}).get("selection") or {}).get("timing_detail") for m in metas if m.get("v2")]
    det = [d for d in det if d]
    for k in sorted({k for d in det for k in d}):
        out[f"td_{k}"] = round(sum(d.get(k, 0) for d in det) / len(det), 2)
    return out


def copy_rate(qs: list[dict]) -> float:
    ds = [key_recall(d, q["answer"]) >= 0.95 for q in qs for d in q["distractors"]]
    return round(sum(ds) / len(ds), 4) if ds else 0.0


def alt_selections(q: dict, meta: dict) -> dict[str, dict]:
    """Cùng tập ứng viên của C4, chọn lại bộ 3 theo từng cách (K4) để so riêng bước chọn."""
    sel = meta["v2"]["selection"]
    alive = [c for c in meta["v2"]["candidates"] if c["rejected_at"] is None and c["score"] is not None]
    out = {}
    for mode in SELECTION_MODES:
        chosen, info = selector.select(sel["key_score"], [c["score"] for c in alive], mode, get_config().distractor.delta,
                                       rng=random.Random(meta["seed_chunk"]), texts=[c["text"] for c in alive],
                                       key_text=q["answer"])
        if chosen is not None:
            out[mode] = {**q, "distractors": [alive[i]["text"] for i in chosen], "entropy": info.get("entropy")}
    return out


def _read_results(path: Path) -> dict[int, tuple]:
    """seed_chunk → (question, meta) từ một file questions_*.jsonl (dòng hỏng ở cuối do bị ngắt thì bỏ qua)."""
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done[r["meta"]["seed_chunk"]] = (r["question"], r["meta"])
    return done


async def run_config(name: str, seeds: list, contexts: dict, out: Path) -> list[tuple]:
    """Sinh câu cho một cấu hình, GHI NGAY từng hạt giống vào questions_<name>.partial.jsonl. Bị ngắt giữa chừng
    (máy ngủ, Docker tắt) thì chạy lại với --resume sẽ bỏ qua các hạt giống đã xong. Xong hết mới đổi tên thành
    questions_<name>.jsonl."""
    final, partial = out / f"questions_{name}.jsonl", out / f"questions_{name}.partial.jsonl"
    if final.exists():
        done = _read_results(final)
        print(f"{name}: đã có {final.name} ({len(done)} hạt giống), bỏ qua.")
        return [done[s.chunk.id] for s in seeds if s.chunk.id in done]
    done = _read_results(partial)
    todo = [s for s in seeds if s.chunk.id not in done]
    print(f"{name}: {len(done)} hạt giống đã xong từ lần trước, còn {len(todo)}.")
    with override(CONFIGS[name]), partial.open("a", encoding="utf-8") as f:
        sem = asyncio.Semaphore(get_config().bank.concurrency)
        n_new = 0

        async def one(s):
            nonlocal n_new
            async with sem:
                q, m = await generate(s, contexts[s.chunk.id])
            f.write(json.dumps({"question": q, "meta": m}, ensure_ascii=False, default=str) + "\n")
            f.flush()
            done[s.chunk.id] = (q, m)
            n_new += 1
            if n_new % 10 == 0:
                print(f"  {name}: {len(done)}/{len(seeds)} hạt giống", flush=True)
        await asyncio.gather(*(one(s) for s in todo))
    results = [done[s.chunk.id] for s in seeds]
    with final.open("w", encoding="utf-8") as f:
        for q, m in results:
            f.write(json.dumps({"question": q, "meta": m}, ensure_ascii=False, default=str) + "\n")
    partial.unlink(missing_ok=True)
    return results


async def main_async(a) -> None:
    out = Path(a.resume) if a.resume else RESULTS / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    args_file = out / "run_args.json"
    if a.docs_like:
        a.docs = resolve_docs(a.docs_like)
    args = {"docs": a.docs, "n_seeds": a.n_seeds, "seed": a.seed}
    if a.per_doc:
        args = {"docs": a.docs, "per_doc": a.per_doc, "seed": a.seed, "balanced": True}
    if args_file.exists() and json.loads(args_file.read_text(encoding="utf-8")) != args:
        raise SystemExit(f"{out} đã chạy với tham số khác {args_file.read_text(encoding='utf-8')}: "
                         "dùng thư mục --resume khác hoặc đúng tham số cũ.")
    args_file.write_text(json.dumps(args), encoding="utf-8")
    seeds = pick_seeds_balanced(a.docs, a.per_doc, a.seed) if a.per_doc else pick_seeds(a.docs, a.n_seeds, a.seed)
    contexts = {s.chunk.id: bb._load_context(s) for s in seeds}
    print(f"{len(seeds)} hạt giống từ bài {a.docs}. Kết quả: {out}")
    rows, sheet = [], []
    by_cfg: dict[str, list[dict]] = {}
    for name in a.configs:
        results = await run_config(name, seeds, contexts, out)
        qs = [q for q, m in results if q and m.get("passed")]
        metas = [m for _, m in results]
        by_cfg[name] = [{"q": q, "meta": m} for q, m in results]
        calls = [len((m.get("v2") or {}).get("llm_calls") or [1]) for m in metas if "failed" not in m]
        row = {"config": name, "n_seeds": len(seeds), "n_ok": len(qs),
               "fail_rate": round(1 - len(qs) / max(len(seeds), 1), 4), "copy_rate": copy_rate(qs),
               "mean_entropy": round(sum(m["v2"]["selection"].get("entropy", 0) for m in metas if m.get("v2"))
                                     / max(sum(1 for m in metas if m.get("v2")), 1), 4) if name != "C0" else "",
               "llm_calls_per_q": round(sum(calls) / max(len(calls), 1), 2),
               "seconds_per_q": round(sum(m.get("seconds", 0) for m in metas) / max(len(metas), 1), 2),
               **(await solver_metrics(qs, a.runs, a.seed) if not a.skip_solver else {})}
        row.update(fail_breakdown(metas))
        row.update(timing_breakdown(metas))
        src = __import__("collections").Counter(
            c["source"] for m in metas for c in ((m.get("v2") or {}).get("candidates") or (m.get("details") or {}).get("pool") or []))
        row["vit5_candidates"], row["llm_candidates"] = src.get("vit5", 0), src.get("llm", 0)
        cfg_sources = CONFIGS[name].get("distractor.sources", get_config().distractor.sources)
        if CONFIGS[name].get("bank.pipeline") == "v2" and "vit5" in cfg_sources and not src.get("vit5"):
            warns = __import__("collections").Counter(w for m in metas for w in m.get("warnings") or [] if "vit5" in w.lower())
            print(f"CẢNH BÁO {name}: ViT5 không sinh ứng viên nào. Lỗi ghi được: {dict(warns.most_common(3)) or 'không có'}")
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        for i, q in enumerate(qs):
            for d in q["distractors"]:
                sheet.append({"_cfg": name, "stem": q["stem"], "dap_an_dung": q["answer"], "dap_an_nhieu": d})

    if "C4" in by_cfg and not a.skip_solver:
        alts: dict[str, list[dict]] = {m: [] for m in SELECTION_MODES}
        for item in by_cfg["C4"]:
            if item["q"] and item["meta"].get("v2"):
                for mode, q in alt_selections(item["q"], item["meta"]).items():
                    alts[mode].append(q)
        for mode, qs in alts.items():
            row = {"config": f"C4/{mode}", "n_ok": len(qs), "copy_rate": copy_rate(qs),
                   "mean_entropy": round(sum(q["entropy"] or 0 for q in qs) / max(len(qs), 1), 4),
                   **await solver_metrics(qs, a.runs, a.seed)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))

    fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "config", k))
    write_csv(out / "metrics.csv", rows, fields)
    rng = random.Random(a.seed)
    rng.shuffle(sheet)
    key = [{"ma": f"D{i + 1:04d}", "cau_hinh": r.pop("_cfg")} for i, r in enumerate(sheet)]
    blind = [{"ma": k["ma"], **r, "chac_chan_sai_0_1": "", "hop_ly_1_3": "", "cung_loai_0_1": "", "ghi_chu": ""}
             for k, r in zip(key, sheet)]
    if blind:
        write_csv(out / "phieu_cham_dap_an_nhieu.csv", blind)
        write_csv(out / "khoa_cau_hinh.csv", key)      # người chấm không mở file này
    print(f"Xong. Bảng chỉ số: {out / 'metrics.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", nargs="+", type=int, help="id các bài học dành riêng cho test")
    ap.add_argument("--docs-like", help='chọn mọi bài có tên file chứa chuỗi này, ví dụ "Chuong" (9 chương NLP)')
    ap.add_argument("--per-doc", type=int, help="chia đều: số hạt giống MỖI bài (bỏ slide tiêu đề, slide hành chính)")
    ap.add_argument("--n-seeds", type=int, default=100)
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=list(CONFIGS))
    ap.add_argument("--runs", type=int, default=3, help="số lần chạy model giải cho mỗi điều kiện")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-solver", action="store_true", help="chỉ sinh câu, không gọi model giải (đỡ tốn API)")
    ap.add_argument("--resume", help="thư mục kết quả để ghi vào / chạy tiếp (mặc định: thư mục mới theo thời điểm)")
    a = ap.parse_args()
    if not (a.docs or a.docs_like):
        ap.error("cần --docs hoặc --docs-like")
    asyncio.run(main_async(a))


if __name__ == "__main__":
    main()
