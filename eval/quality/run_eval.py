"""Chạy bộ đánh giá chất lượng câu trắc nghiệm trên các file data/<phiên bản>_items.jsonl (tạo bằng export.py).

Lớp đã cài:
  A  chỉ số theo luật A1–A12 (không cần mô hình, chạy được ngoài container)
  E  chỉ số embedding E1–E4 và A13 (bge-m3, chạy trong container API)
  S  solver P6–P8 và J  LLM judge P1–P5 (metrics/llm_eval.py); mô hình đánh giá đặt ở config.yaml → eval_models,
     phải khác họ với mô hình sinh câu hỏi. Kết quả gọi mô hình được lưu đệm (cache/llm_cache.jsonl).

Ví dụ (trong container):
  python -m eval.quality.run_eval --layers A E
  python -m eval.quality.run_eval --layers A E S J
  python -m eval.quality.run_eval --layers A S J --versions V1 V2 --limit 10     # chạy thử 10 câu mỗi phiên bản
Kết quả: eval/quality/results/<thời điểm>/ gồm per_item_<phiên bản>.csv, summary.csv, diff.csv, set_level.csv,
report.md.
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from eval.quality import core, stats
from eval.quality.common import ROOT, load_cfg, read_jsonl
from eval.quality.metrics import rules

TARGET_25 = {"A1_key_longest", "A1b_key_shortest", "A4_stem_overlap_cue", "A7_key_closest_to_slide",
             "A10_key_convergent"}
LLM_STATS: dict = {}


def columns(layers: list[str]) -> dict:
    cols = dict(rules.PER_ITEM_COLUMNS)
    cols.update(core.COLUMNS)
    cols["A12_leaked"] = ("Đáp án câu này lộ trong câu hỏi khác cùng bài", "T2", "0")
    if "E" in layers:
        from eval.quality.metrics import embed
        cols.update(embed.PER_ITEM_COLUMNS)
        cols["A13_dup_stem"] = ("Câu hỏi trùng câu khác (cos > 0,9)", "T3", "0")
    if "S" in layers or "J" in layers:
        from eval.quality.metrics import llm_eval
        if "S" in layers:
            cols.update(llm_eval.S_COLUMNS)
        if "J" in layers:
            cols.update(llm_eval.J_COLUMNS)
    return cols


def evaluate(items: list[dict], cfg: dict) -> tuple[list[dict], dict]:
    """Lớp A theo luật cho một phiên bản."""
    rows = [{"item_id": it["item_id"], "version": it["version"], "chunk_id": it["chunk_id"], "doc_id": it.get("doc_id"),
             "key": it["key"], "stem": it["stem"], **rules.per_item(it, cfg), **core.per_item(it)} for it in items]
    set_level = {"n_items": len(items), **rules.key_position(items)}
    leak, flags = rules.cross_leak(items, cfg)
    set_level.update(leak)
    for r in rows:
        r["A12_leaked"] = flags[r["item_id"]]
    return rows, set_level


def add_embedding(per_version: dict, items: dict, set_rows: list[dict], cfg: dict) -> tuple[dict, dict]:
    """Lớp E: mã hoá mọi phiên bản một lần, hiệu chỉnh MỘT bộ ngưỡng chung, rồi tính theo từng câu.
    Trả (ngưỡng đã hiệu chỉnh, dữ liệu thô theo item_id cho phân tích độ nhạy)."""
    from eval.quality.metrics import embed

    th = cfg["thresholds"]
    all_items = [it for v in per_version for it in items[v]]
    raw = embed.raw_similarities(all_items)
    cal = embed.calibrate(raw, th)
    by_id = {(r["version"], r["item_id"]): r for r in raw}
    for v, rows in per_version.items():
        for r in rows:
            r.update(embed.per_item(by_id[(v, r["item_id"])], cal, th))
        dup, flags = embed.dup_stems([by_id[(v, r["item_id"])] for r in rows], th)
        next(s for s in set_rows if s["version"] == v).update(dup)
        for r in rows:
            r["A13_dup_stem"] = flags[r["item_id"]]
    return cal, by_id


def sensitivity(per_version: dict, cal: dict | None, raw: dict | None, cfg: dict) -> list[dict]:
    """Checklist mục 11: mỗi ngưỡng thử ± cfg.thresholds.sensitivity, các ngưỡng khác giữ nguyên."""
    th, step = cfg["thresholds"], cfg["thresholds"]["sensitivity"]
    out = []
    for v, rows in per_version.items():
        base = th["length_ratio_max"]
        for r_ in (base - step, base, base + step):
            out.append({"version": v, "metric": "A3_len_violation", "threshold": f"max/min > {r_:.2f}",
                        "value": stats.mean([float(r["_len_ratio"] > r_) for r in rows])})
        if cal is None:
            continue
        from eval.quality.metrics import embed
        variants = [("E2_in_band", f"a={a:.2f}, b={b:.2f}", {"band_low": a, "band_high": b})
                    for a, b in ((cal["band_low"] - step, cal["band_high"]), (cal["band_low"] + step, cal["band_high"]),
                                 (cal["band_low"], cal["band_high"] - step), (cal["band_low"], cal["band_high"] + step))]
        if cal["topic_tau"] is not None:
            variants += [("E3_off_topic", f"τ={t:.3f}", {"tau": t})
                         for t in (cal["topic_tau"] - step, cal["topic_tau"] + step)]
        for metric, label, kw in variants:
            vals = [embed.per_item(raw[(v, r["item_id"])], cal, th, **kw)[metric] for r in rows]
            out.append({"version": v, "metric": metric, "threshold": label, "value": stats.mean(vals)})
    return out


def fmt(x, nd=3) -> str:
    return "" if x is None else f"{x:.{nd}f}"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def cost_report(usage: dict, n_scored: int, n_full: int, a, cfg: dict) -> str:
    """Chi phí thật của lần chạy này và ước tính khi chấm toàn bộ (cùng mô hình, cùng số lần gọi mỗi câu)."""
    if not usage or not usage.get("calls"):
        return ""
    calls, usd = usage["calls"], usage["usd"]
    n_solvers = len(cfg["eval_models"]["solvers"])
    runs = (cfg.get("eval_llm") or {}).get("runs", 1)
    s_calls = (3 * n_solvers * runs) if "S" in a.layers else 0
    j_calls = len((cfg.get("eval_llm") or {}).get("judge_prompts") or "12345") if "J" in a.layers else 0
    per_item = usd / max(n_scored, 1)
    lines = ["", "===== CHI PHÍ GỌI MÔ HÌNH ĐÁNH GIÁ (lần chạy này) =====",
             f"Số câu chấm: {n_scored} · lần gọi mới: {calls} · token vào {usage['in']:,} · token ra {usage['out']:,}"]
    for m, d in usage.get("by_model", {}).items():
        lines.append(f"  {m}: {d['calls']} lần gọi, {d['in']:,} + {d['out']:,} token, {d['usd']:.4f} USD")
    if usage.get("usd_known", True) and usd > 0:
        lines += [f"Tổng: {usd:.4f} USD  →  trung bình {per_item:.5f} USD / câu ({s_calls + j_calls} lần gọi / câu)",
                  f"ƯỚC TÍNH chấm TOÀN BỘ {n_full} câu (lớp {' + '.join(x for x in ('S', 'J') if x in a.layers)}): "
                  f"≈ {per_item * n_full:.2f} USD"]
        if s_calls and j_calls:
            share = s_calls / (s_calls + j_calls)
            lines += [f"  · chỉ lớp S (M1, M2): ≈ {per_item * n_full * share:.2f} USD",
                      f"  · chỉ lớp J (M1b và giám khảo): ≈ {per_item * n_full * (1 - share):.2f} USD"]
        lines.append("Phần đã chấm được lưu đệm: chạy toàn bộ sau đó KHÔNG trả lại tiền cho các câu này.")
    else:
        lines.append("LiteLLM chưa có bảng giá cho mô hình này: xem chi phí thật ở trang Usage của OpenAI "
                     "(platform.openai.com/usage) và chia cho số câu ở trên.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--layers", nargs="+", default=["A"], choices=["A", "E", "S", "J"])
    ap.add_argument("--versions", nargs="*", help="mặc định: mọi file *_items.jsonl trong --data")
    ap.add_argument("--limit", type=int, help="chỉ lấy N câu đầu mỗi phiên bản (chạy thử lớp S/J cho đỡ tốn)")
    ap.add_argument("--sample", type=int, help="lấy N chunk ngẫu nhiên (seed cố định) CHUNG cho mọi phiên bản: "
                                               "so sánh theo cặp mà ít lần gọi mô hình (gói miễn phí)")
    ap.add_argument("--solvers", nargs="+", help="ghi đè eval_models.solvers")
    ap.add_argument("--judge", help="ghi đè eval_models.judge (ví dụ openai/gpt-6-sol để chấm ngay, có phí)")
    ap.add_argument("--runs", type=int, help="ghi đè eval_llm.runs")
    ap.add_argument("--judge-prompts", nargs="+", choices=["P1", "P2", "P3", "P4", "P5"],
                    help="chỉ chạy các prompt giám khảo này (P2 = có ≥ 2 đáp án đúng, cho M1b) để tiết kiệm")
    ap.add_argument("--base", help="phiên bản làm mốc để tính hiệu (mặc định config: V1), ví dụ LLM-GPT")
    ap.add_argument("--max-usd", type=float, help="trần chi phí gọi mô hình của lần chạy (chạm trần thì dừng, giữ phần đã chấm)")
    a = ap.parse_args()
    cfg = load_cfg()
    if a.solvers:
        cfg["eval_models"] = {**cfg["eval_models"], "solvers": a.solvers}
    if a.judge:
        cfg["eval_models"] = {**cfg["eval_models"], "judge": a.judge}
    if a.runs:
        cfg["eval_llm"] = {**(cfg.get("eval_llm") or {}), "runs": a.runs}
    if a.judge_prompts:
        cfg["eval_llm"] = {**(cfg.get("eval_llm") or {}), "judge_prompts": a.judge_prompts}
    if a.max_usd is not None:
        cfg["eval_llm"] = {**(cfg.get("eval_llm") or {}), "max_usd": a.max_usd}
    data = Path(a.data)
    files = {p.name.removesuffix("_items.jsonl"): p for p in sorted(data.glob("*_items.jsonl"))}
    if a.versions:
        files = {v: files[v] for v in a.versions if v in files}
    if not files:
        raise SystemExit(f"Không có file *_items.jsonl trong {data}. Chạy export.py trước.")
    base = a.base or cfg["baseline"]
    out = ROOT / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    cols = columns(a.layers)

    per_version, set_rows, items = {}, [], {}
    loaded = {v: read_jsonl(path) for v, path in files.items()}
    n_full = sum(len(xs) for xs in loaded.values())          # để ngoại suy chi phí khi chạy thử trên mẫu
    if a.sample:
        import random as _r
        common_all = sorted(set.intersection(*({it["chunk_id"] for it in xs} for xs in loaded.values())))
        keep = set(_r.Random(cfg["seed"]).sample(common_all, min(a.sample, len(common_all))))
        loaded = {v: [it for it in xs if it["chunk_id"] in keep] for v, xs in loaded.items()}
        print(f"Mẫu {len(keep)} chunk chung (seed {cfg['seed']}).")
    for v in files:
        items[v] = loaded[v][:a.limit] if a.limit else loaded[v]
        rows, sl = evaluate(items[v], cfg)
        per_version[v] = rows
        set_rows.append({"version": v, **sl})
        print(f"{v}: {len(rows)} câu")
    cal, raw = add_embedding(per_version, items, set_rows, cfg) if "E" in a.layers else (None, None)
    if "S" in a.layers or "J" in a.layers:
        import asyncio
        from eval.quality.metrics import llm_eval
        print("Lớp S/J: gọi mô hình đánh giá...")
        LLM_STATS.update(asyncio.run(llm_eval.run_layers(per_version, items, a.layers, cfg)))
        cost_md = cost_report(LLM_STATS.get("usage") or {}, sum(len(x) for x in items.values()), n_full, a, cfg)
        if cost_md:
            (out / "chi_phi.txt").write_text(cost_md, encoding="utf-8")
            print(cost_md)
        if LLM_STATS.get("budget_hit"):
            print(f"  ⚠ Chạm trần chi phí: còn {LLM_STATS['skipped_calls']} lần gọi chưa làm (các câu đó để trống). "
                  "Muốn chấm nốt: chạy lại với --max-usd lớn hơn; phần đã chấm lấy từ bộ đệm, không trả tiền lại.")
        if LLM_STATS.get("quota_exhausted"):
            print(f"  ⚠ Hết hạn mức ngày: {', '.join(LLM_STATS['quota_exhausted'])} — còn {LLM_STATS['skipped_calls']} "
                  "lần gọi chưa làm. Kết quả đã chấm được lưu đệm; CHẠY LẠI vào ngày mai để chấm tiếp.")
        if LLM_STATS.get("errors"):
            print(f"  Lỗi khi gọi mô hình: {LLM_STATS['errors']}")
            if not LLM_STATS.get("new_calls") and not any(
                    r.get(c) is not None for rows in per_version.values() for r in rows
                    for c in (*llm_eval.S_COLUMNS, *llm_eval.J_COLUMNS)):
                raise SystemExit("Mọi lần gọi mô hình đánh giá đều lỗi: kiểm tra API key và tên mô hình trong "
                                 "eval/quality/config.yaml → eval_models.")
    for v, rows in per_version.items():
        write_csv(out / f"per_item_{v}.csv", [{k: x for k, x in r.items() if not k.startswith("_")} for r in rows])
    sens = sensitivity(per_version, cal, raw, cfg)
    write_csv(out / "sensitivity.csv", sens)

    # Phạm vi so sánh: mọi câu, và chỉ các chunk mà mọi phiên bản đều sinh được câu (công bằng với V2)
    common = set.intersection(*(set(r["chunk_id"] for r in rows) for rows in per_version.values()))
    scopes = {"all": per_version,
              "common": {v: [r for r in rows if r["chunk_id"] in common] for v, rows in per_version.items()}}
    summary = []
    for scope, by_v in scopes.items():
        for v, rows in by_v.items():
            for col, (desc, code, target) in cols.items():
                vals = [r.get(col) for r in rows]
                m = stats.mean(vals)
                lo, hi = stats.bootstrap_ci(rows, col, cfg["bootstrap"], cfg["seed"])
                p = None
                if col in TARGET_25:
                    n = sum(x is not None for x in vals)
                    p = stats.binom_two_sided(round(sum(x for x in vals if x is not None)), n)
                summary.append({"scope": scope, "version": v, "metric": col, "n": len(rows), "value": m,
                                "ci_lo": lo, "ci_hi": hi, "p_vs_0.25": p, "target": target, "code": code,
                                "description": desc})
    diffs = []
    if base in per_version:
        for v, rows in per_version.items():
            if v == base:
                continue
            for col in cols:
                d, lo, hi, n = stats.bootstrap_diff(per_version[base], rows, col, cfg["bootstrap"], cfg["seed"])
                sig = None if lo is None else (lo > 0 or hi < 0)
                diffs.append({"version": v, "vs": base, "metric": col, "n_common_chunks": n, "diff": d,
                              "ci_lo": lo, "ci_hi": hi, "significant": sig})
    write_csv(out / "summary.csv", summary)
    write_csv(out / "diff.csv", diffs)
    write_csv(out / "set_level.csv", set_rows)
    yields = []
    if (data / "yield.csv").exists():
        with open(data / "yield.csv", encoding="utf-8-sig") as f:
            yields = list(csv.DictReader(f))
    core_rows, core_md = core.table(per_version, items, base, a.layers, cfg, yields)
    write_csv(out / "core.csv", core_rows)
    full = report(summary, diffs, set_rows, yields, cols, list(per_version), base, len(common), a.layers, data, cal,
                  sens)
    head, _, rest = full.partition("\n## ")                 # bảng chỉ số chính đứng ngay sau phần mở đầu
    (out / "report.md").write_text(f"{head}\n{core_md}\n## {rest}" if rest else f"{full}\n{core_md}",
                                   encoding="utf-8")
    print("\n" + core_md)
    (out / "run.json").write_text(json.dumps({"data": str(data), "layers": a.layers, "versions": list(files), "base": base,
                                              "thresholds": cfg["thresholds"], "calibrated": cal,
                                              "llm_eval": LLM_STATS or None, "limit": a.limit,
                                              "sample": a.sample},
                                             ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Xong: {out}")
    if LLM_STATS.get("quota_exhausted"):
        raise SystemExit(3)          # .bat hiểu: chưa chấm xong, chạy lại hôm sau


def report(summary, diffs, set_rows, yields, cols, versions, base, n_common, layers, data, cal, sens) -> str:
    get = {(s["scope"], s["version"], s["metric"]): s for s in summary}
    dget = {(d["version"], d["metric"]): d for d in diffs}
    main = [v for v in (base, "V2") if v in versions]
    lines = [f"# Báo cáo chất lượng câu trắc nghiệm", "",
             f"Dữ liệu: `{data}` · lớp: {', '.join(layers)} · chunk chung của mọi phiên bản: {n_common}", ""]
    if cal:
        lines += [f"Ngưỡng embedding (một bộ chung cho mọi phiên bản): E2 [a, b] = [{cal['band_low']}, "
                  f"{cal['band_high']}]; E2 kèm câu hỏi = [{cal['band_stem_low']:.3f}, {cal['band_stem_high']:.3f}] "
                  f"(phân vị {cal.get('band_stem_quantiles')}); E3 τ = {fmt(cal['topic_tau'])} "
                  "(trung vị cos của đáp án nhiễu với slide câu khác).", ""]
    if yields:
        lines += ["## Tỉ lệ sinh được", "", "| Phiên bản | Cấu hình | Hạt giống | Câu đạt | Tỉ lệ |", "|---|---|---|---|---|"]
        lines += [f"| {y['version']} | {y['config']} | {y['n_seeds']} | {y['n_ok']} | {y['yield']} |" for y in yields]
        lines.append("")
    for target in ("V2", "V3"):            # mỗi phiên bản chính so với mốc (V1)
        main = [v for v in (base, target) if v in versions]
        if len(main) != 2:
            continue
        lines += [f"## {main[0]} so với {main[1]} (mọi câu; hiệu tính trên chunk chung)", "",
                  f"| Chỉ số | Mã | {main[0]} | {main[1]} | Hiệu {main[1]}−{main[0]} (CI 95%) | Mục tiêu |",
                  "|---|---|---|---|---|---|"]
        for col, (desc, code, target_txt) in cols.items():
            cells = []
            for v in main:
                s_ = get.get(("all", v, col))
                cells.append(f"{fmt(s_['value'])} [{fmt(s_['ci_lo'], 2)}, {fmt(s_['ci_hi'], 2)}]" if s_ and s_["value"] is not None else "")
            d = dget.get((main[1], col))
            dcell = (f"{fmt(d['diff'])} [{fmt(d['ci_lo'], 2)}, {fmt(d['ci_hi'], 2)}]{' *' if d['significant'] else ''}"
                     if d and d["diff"] is not None else "")
            lines.append(f"| {desc} | {code} | {cells[0]} | {cells[1]} | {dcell} | {target_txt} |")
        lines += ["", "`*` = CI 95% của hiệu không chứa 0.", ""]
    lines += ["## Ablation (mọi câu)", "", "| Chỉ số | " + " | ".join(versions) + " |",
              "|---|" + "---|" * len(versions)]
    for col, (desc, _, _) in cols.items():
        vals = [get.get(("all", v, col)) for v in versions]
        lines.append(f"| {desc} | " + " | ".join(fmt(s["value"]) if s else "" for s in vals) + " |")
    lines += ["", "## Chỉ số trên cả tập", "", "| Phiên bản | Số câu | Vị trí key (A11) | p chi² | Lộ chéo (A12) | Trùng câu hỏi (A13) |",
              "|---|---|---|---|---|---|"]
    for s in set_rows:
        lines.append(f"| {s['version']} | {s['n_items']} | {s['A11_key_counts']} | {fmt(s['A11_p'])} | "
                     f"{fmt(s.get('A12_leak_pair_rate'))} | {fmt(s.get('A13_dup_pair_rate'))} |")
    lines += ["", "A11: hệ thống xáo phương án ngẫu nhiên khi lưu vào ngân hàng (`shuffle_options`), `export.py` cũng "
              "xáo như vậy. Vị trí đáp án đúng vì thế đều theo thiết kế; p < 0,05 ở một vài phiên bản chỉ phản ánh "
              "một lần xáo.", ""]
    if sens:
        lines += ["## Độ nhạy theo ngưỡng", "", "| Phiên bản | Chỉ số | Ngưỡng | Giá trị |", "|---|---|---|---|"]
        lines += [f"| {s['version']} | {s['metric']} | {s['threshold']} | {fmt(s['value'])} |" for s in sens
                  if s["version"] in (base, "V2", "V3")]
        lines.append("")
    lines += ["", "## Hạn chế", "",
              "- a, b, 1,5 và 0,9 là giá trị khởi đầu của đặc tả; τ và dải kèm câu hỏi được hiệu chỉnh theo phân bố "
              "nhưng không có nhãn người. Xem bảng độ nhạy trước khi kết luận.",
              "- Tách từ theo âm tiết và danh sách hư từ tự soạn, không dùng bộ tách từ tiếng Việt.",
              "- A5 và các luật độ dài là luật mà V2 dùng để lọc: hiệu của V2 ở các chỉ số này một phần do thiết kế.",
              "- E1/E2 dùng bge-m3, cùng họ với bộ xếp hạng của V2.",
              *([f"- Lớp S/J: judge `{LLM_STATS.get('judge')}`, solver {LLM_STATS.get('solvers')}, "
                 f"{LLM_STATS.get('runs')} lần chạy mỗi điều kiện. Judge LLM chưa được đối chiếu với người chấm."]
                if LLM_STATS else
                ["- Chưa có lớp J (judge), S (solver): chưa kết luận được về tính đúng duy nhất và độ khó."]),
              "- Chưa có đánh giá người cho phiên bản này.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
