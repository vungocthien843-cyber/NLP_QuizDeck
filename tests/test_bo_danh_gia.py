"""Bộ đánh giá hoàn chỉnh: bảng chỉ số chính (eval/quality/core.py) và báo cáo tổng hợp 3 tầng (eval/tong_hop.py)."""
import json
import sys

from eval.quality import core


def _item(v, c, key_len=4, dist_lens=(3, 4, 5), types=None):
    opts = {"A": " ".join(["k"] * key_len) + f" đáp{c}"}
    for L, n in zip("BCD", dist_lens, strict=True):
        opts[L] = " ".join([f"d{L}{c}"] * n) + f" sai {L}"
    return {"item_id": f"{v.lower()}_{c}", "version": v, "chunk_id": c, "doc_id": 1, "stem": f"Câu {c} hỏi gì?",
            "options": opts, "key": "A", "source_context": f"slide {c} nói về k", "evidence": "k",
            "bloom_target": "remember", "error_types": types}


def test_core_per_item_and_rank_test():
    it = _item("V3", 1, key_len=4, dist_lens=(1, 1, 5),          # số từ: key 5, phương án sai 3, 3, 7
               types={"B": "dao_nhan_qua", "C": "sai_mot_chi_tiet", "D": "khong_ro"})
    x = core.per_item(it)
    assert x["C_coverage"] == 1.0 and 0 < x["C_distinct2"] <= 1 and x["C_key_len_rank"] == 2
    assert core.per_item({**it, "error_types": {"B": "khong_ro", "C": "khong_ro", "D": "dao_nhan_qua"}})["C_coverage"] == 0
    assert core.per_item({**it, "error_types": None})["C_coverage"] is None
    rt = core.length_rank_test([_item("V1", c, key_len=9) for c in range(20)])       # key luôn dài nhất
    assert rt["M5c_rank_counts"] == [0, 0, 0, 20] and rt["M5c_p"] < 0.05


def test_full_suite_core_table_and_summary(tmp_path, monkeypatch):
    from eval import tong_hop
    from eval.quality import run_eval
    from eval.quality.metrics import llm_eval

    data = tmp_path / "data"
    data.mkdir()
    for v in ("V1", "V3"):
        types = {"B": "dao_nhan_qua", "C": "sai_mot_chi_tiet", "D": "nham_khai_niem_lan_can"} if v == "V3" else None
        rows = [_item(v, c, types=types) for c in range(12)]
        (data / f"{v}_items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                               encoding="utf-8")

    async def fake(model, prompt, temperature):
        return '{"answer": "A"}'
    monkeypatch.setattr(llm_eval, "_litellm_complete", fake)
    monkeypatch.setattr(llm_eval, "CACHE", tmp_path / "cache.jsonl")
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    base_cfg = run_eval.load_cfg()
    monkeypatch.setattr(run_eval, "load_cfg", lambda p=None: {
        **base_cfg, "bootstrap": 200, "eval_llm": {"runs": 1, "cache": False, "concurrency": 4}})
    monkeypatch.setattr(sys, "argv", ["x", "--data", str(data), "--layers", "A", "S", "--judge", "x/j",
                                      "--solvers", "y/s"])
    run_eval.main()
    out = next((tmp_path / "results").iterdir())
    rows = {(r["code"], r["version"]): r for r in tong_hop.read_csv(out / "core.csv")}
    assert tong_hop.num(rows[("M1", "V1")]["value"]) is not None      # lớp S chạy (người giải giả)
    assert float(rows[("M6", "V3")]["value"]) == 1.0 and rows[("M6", "V1")]["value"] in ("", "None")
    assert rows[("M5", "V3")]["verdict"] in ("✅", "❌")
    rep = (out / "report.md").read_text(encoding="utf-8")
    assert rep.index("## Chỉ số chính") < rep.index("## V1 so với V3")

    monkeypatch.setattr(tong_hop, "QUALITY", tmp_path / "results")
    monkeypatch.setattr(tong_hop, "HUMAN", tmp_path / "khong_co")
    monkeypatch.setattr(tong_hop, "STUDENT", tmp_path / "khong_co")
    monkeypatch.setattr(tong_hop, "OUT", tmp_path / "BAO_CAO.md")
    tong_hop.main()
    md = (tmp_path / "BAO_CAO.md").read_text(encoding="utf-8")
    assert "Open-book Solver Accuracy" in md and "Misconception Coverage" in md
    assert "Tầng 2" in md and "Chưa có" in md and "⏳" in md
