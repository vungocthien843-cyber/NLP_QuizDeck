"""Chuyển kết quả của eval/v2/run_ablation sang định dạng câu hỏi của bộ đánh giá (mục 3 của đặc tả).

Mỗi phiên bản một file data/<phiên bản>_items.jsonl. Chỉ lấy câu đã qua hậu kiểm (passed). Phương án được xáo
thứ tự cố định theo seed và item_id, nên chạy lại cho ra đúng cùng file. Kèm data/yield.csv: số câu sinh được trên
số hạt giống của mỗi phiên bản (V2 tự loại câu khó, nên chỉ so trên câu đạt sẽ thiên vị V2).

Chạy trong container API (cần DB để lấy chương/bài và selector để tạo biến thể chọn bộ 3):
  python -m eval.quality.export --results eval/v2/results/<thời điểm>
"""
import argparse
import csv
import json
import random
from pathlib import Path

from eval.quality.common import LETTERS, ROOT, load_cfg, read_jsonl, write_jsonl


def chunk_info(chunk_ids: set[int]) -> dict[int, dict]:
    try:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import Chunk
        with SessionLocal() as db:
            rows = db.execute(select(Chunk.id, Chunk.document_id, Chunk.chapter_no, Chunk.slide_no)
                              .where(Chunk.id.in_(chunk_ids))).all()
        return {r.id: {"doc_id": r.document_id, "chapter": r.chapter_no, "slide": r.slide_no} for r in rows}
    except Exception as exc:          # chạy ngoài container: không có DB
        print(f"Không đọc được DB ({type(exc).__name__}); bỏ trống chương/bài.")
        return {}


def make_item(version: str, q: dict, meta: dict, info: dict, seed: int) -> dict:
    chunk_id = meta["seed_chunk"]
    item_id = f"{version.lower()}_{chunk_id}"
    texts = [q["answer"], *q["distractors"]]
    order = list(range(len(texts)))
    random.Random(f"{seed}:{item_id}").shuffle(order)
    options = {LETTERS[i]: texts[j] for i, j in enumerate(order)}
    key = LETTERS[order.index(0)]
    ci = info.get(chunk_id, {})
    # Loại hiểu nhầm của từng phương án sai (chỉ có ở V3: lấy theo văn bản từ v2.picked / kho ứng viên)
    pool = {c["text"]: c for c in ((meta.get("v2") or {}).get("candidates") or [])}
    pool.update({p["text"]: p for p in ((meta.get("v2") or {}).get("picked") or [])})
    error_types = ({L: (pool.get(t) or {}).get("error_type") for L, t in options.items() if L != key}
                   if pool else None)
    return {"item_id": item_id, "version": version, "chunk_id": chunk_id, "doc_id": ci.get("doc_id"),
            "chapter": ci.get("chapter"), "slide": ci.get("slide"), "source_context": q.get("context", ""),
            "concept": None,
            "stem": q["stem"], "options": options, "key": key, "bloom_target": meta.get("bloom"),
            "evidence": q.get("evidence"), "error_types": error_types,
            "sources": ({L: (pool.get(t) or {}).get("source") for L, t in options.items() if L != key}
                        if pool else None)}


def selection_variants(rec: dict, modes: dict[str, str]) -> dict[str, dict]:
    """Chọn lại bộ 3 trên kho ứng viên đã lưu của một câu C4 (giống alt_selections của run_ablation)."""
    from app.config import get_config
    from app.generation import selector

    meta, q = rec["meta"], rec["question"]
    sel = meta["v2"]["selection"]
    alive = [c for c in meta["v2"]["candidates"] if c["rejected_at"] is None and c.get("score") is not None]
    out = {}
    for mode, version in modes.items():
        chosen, _ = selector.select(sel["key_score"], [c["score"] for c in alive], mode,
                                    get_config().distractor.delta, rng=random.Random(meta["seed_chunk"]),
                                    texts=[c["text"] for c in alive], key_text=q["answer"])
        if chosen is not None:
            out[version] = {**q, "distractors": [alive[i]["text"] for i in chosen]}
    return out


def source_variants(rec: dict, modes: dict[str, str]) -> dict[str, dict]:
    """Ablation nguồn sinh (C5): chọn lại bộ 3 khi CHỈ cho phép ứng viên của một nguồn (vit5 hoặc llm), cùng thuật
    toán chọn và mọi ràng buộc của V3. Xấp xỉ offline: chạy thật một nguồn thì bước sinh bù có thể thêm ứng viên."""
    from app.config import get_config
    from app.generation import selector

    meta, q = rec["meta"], rec["question"]
    sel = meta["v2"]["selection"]
    out = {}
    for source, version in modes.items():
        alive = [c for c in meta["v2"]["candidates"]
                 if c.get("rejected_at") is None and c.get("score") is not None and c.get("source") == source]
        chosen, _ = selector.select(sel["key_score"], [c["score"] for c in alive], "entropy",
                                    get_config().distractor.delta, texts=[c["text"] for c in alive],
                                    key_text=q["answer"], error_types=[c.get("error_type") for c in alive])
        if chosen is not None:
            out[version] = {**q, "distractors": [alive[i]["text"] for i in chosen]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, help="thư mục kết quả của eval/v2/run_ablation")
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--no-variants", action="store_true", help="không tạo biến thể chọn bộ 3 (cần app)")
    a = ap.parse_args()
    cfg = load_cfg()
    src, out = Path(a.results), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    loaded = {c: read_jsonl(src / f"questions_{c}.jsonl") for c in cfg["versions"]
              if (src / f"questions_{c}.jsonl").exists()}
    if not loaded:
        raise SystemExit(f"Không thấy questions_C*.jsonl trong {src}")
    info = chunk_info({r["meta"]["seed_chunk"] for recs in loaded.values() for r in recs})

    items: dict[str, list[dict]] = {}
    yields = []
    for cfg_name, recs in loaded.items():
        version = cfg["versions"][cfg_name]
        ok = [r for r in recs if r.get("question") and r["meta"].get("passed")]
        items[version] = [make_item(version, r["question"], r["meta"], info, cfg["seed"]) for r in ok]
        yields.append({"version": version, "config": cfg_name, "n_seeds": len(recs), "n_ok": len(ok),
                       "yield": round(len(ok) / max(len(recs), 1), 4)})
        if cfg_name == "C4" and not a.no_variants:
            try:
                for r in ok:
                    for v, q in selection_variants(r, cfg["selection_variants"]).items():
                        items.setdefault(v, []).append(make_item(v, q, r["meta"], info, cfg["seed"]))
                for v in cfg["selection_variants"].values():
                    yields.append({"version": v, "config": "C4 (chọn lại)", "n_seeds": len(ok),
                                   "n_ok": len(items.get(v, [])),
                                   "yield": round(len(items.get(v, [])) / max(len(ok), 1), 4)})
            except ImportError as exc:
                print(f"Bỏ qua biến thể chọn bộ 3 (thiếu app: {exc}).")
        if cfg_name == "C5" and not a.no_variants and cfg.get("source_variants"):
            try:
                for r in ok:
                    for v, q in source_variants(r, cfg["source_variants"]).items():
                        items.setdefault(v, []).append(make_item(v, q, r["meta"], info, cfg["seed"]))
                for v in cfg["source_variants"].values():
                    yields.append({"version": v, "config": "C5 (một nguồn)", "n_seeds": len(recs),
                                   "n_ok": len(items.get(v, [])),
                                   "yield": round(len(items.get(v, [])) / max(len(recs), 1), 4)})
            except ImportError as exc:
                print(f"Bỏ qua ablation nguồn sinh (thiếu app: {exc}).")

    for version, rows in items.items():
        write_jsonl(out / f"{version}_items.jsonl", rows)
        print(f"{version}: {len(rows)} câu → {out / f'{version}_items.jsonl'}")
    with open(out / "yield.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(yields[0]))
        w.writeheader()
        w.writerows(yields)
    (out / "source.json").write_text(json.dumps({"results": str(src)}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
