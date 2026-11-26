"""Chọn lại bộ 3 đáp án nhiễu của kết quả C5 trên KHO ỨNG VIÊN ĐÃ LƯU, không sinh lại (không tốn API).

Dùng sau khi sửa bước chọn bộ (app/generation/selector.py), ví dụ ràng buộc hạng độ dài của key thêm sau G1 (15/11):
V3 làm key thành phương án ngắn nhất ở 41% câu. Ghi đè questions_C5.jsonl (bản cũ giữ ở
questions_C5.truoc_chon_lai.jsonl; chạy lại thì luôn chọn từ bản cũ đó, nên chạy bao nhiêu lần cũng cho cùng kết quả).

  python -m eval.v2.reselect --results eval/v2/results/G1
"""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path


def reselect(rec: dict) -> tuple[dict, str | None]:
    from app.config import get_config
    from app.generation import selector

    meta, q = rec["meta"], rec.get("question")
    v2 = meta.get("v2") or {}
    if not q or not meta.get("passed") or not v2.get("candidates"):
        return rec, None
    sel = v2["selection"]
    alive = [c for c in v2["candidates"] if c.get("rejected_at") is None and c.get("score") is not None]
    chosen, info = selector.select(sel["key_score"], [c["score"] for c in alive], sel.get("mode", "entropy"),
                                   sel.get("delta", get_config().distractor.delta),
                                   texts=[c["text"] for c in alive], key_text=q["answer"],
                                   error_types=[c.get("error_type") for c in alive])
    if chosen is None:
        return rec, "khong_chon_duoc"
    picked = [alive[i] for i in chosen]
    chosen_texts = {c["text"] for c in picked}
    keep = {k: sel[k] for k in ("scorer", "key_score", "round", "key_entail", "nli_modes", "vit5", "tagging",
                                "neighbors", "timing_detail") if k in sel}
    new_v2 = {**v2, "selection": {**keep, **info, "reselected": True},
              "candidates": [{**c, "selected": c["text"] in chosen_texts} for c in v2["candidates"]],
              "picked": [{k: c.get(k) for k in ("text", "source", "error_type", "error_type_self", "score")}
                         for c in picked]}
    new_q = {**q, "distractors": [c["text"] for c in picked]}
    return {**rec, "question": new_q, "meta": {**meta, "v2": new_v2}}, info.get("form_level")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="eval/v2/results/G1")
    ap.add_argument("--config", default="C5")
    a = ap.parse_args()
    path = Path(a.results) / f"questions_{a.config}.jsonl"
    backup = path.with_name(f"questions_{a.config}.truoc_chon_lai.jsonl")
    if not backup.exists():
        shutil.copy(path, backup)
    recs = [json.loads(x) for x in backup.read_text(encoding="utf-8").splitlines() if x.strip()]
    out, levels, changed = [], Counter(), 0
    for r in recs:
        new, lv = reselect(r)
        if lv:
            levels[lv] += 1
        if new.get("question") and r.get("question") and new["question"]["distractors"] != r["question"]["distractors"]:
            changed += 1
        out.append(new)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(f"Chọn lại {sum(levels.values())} câu, đổi bộ đáp án nhiễu ở {changed} câu. Mức ràng buộc: {dict(levels)}")
    print(f"Bản cũ: {backup.name}; bản mới ghi đè {path.name}")


if __name__ == "__main__":
    main()
