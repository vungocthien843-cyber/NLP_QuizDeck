"""Bảng CHỈ SỐ CHÍNH của bộ đánh giá tự động (docs/bo-danh-gia.md): 5 độ đo cốt lõi + 1 độ đo riêng của V3.

Mỗi độ đo có tên chuẩn, công thức, ngưỡng đạt; tính trên từng câu rồi gộp theo phiên bản, kèm CI 95% bootstrap theo
chunk và hiệu so với mốc (V1) trên các chunk chung. Bảng này đứng đầu report.md; chi tiết ở core.csv.

  M1  Open-book Solver Accuracy  (+ M1b Ambiguity Rate)          câu đúng, một đáp án      lớp S (+ J)
  M2  Choices-only Accuracy                                       không đoán mò được        lớp S
  M3  Semantic Plausibility Rate (+ M3b Off-topic Rate)           phương án nhiễu hợp lý    lớp E
  M4  Near-duplicate Rate        (+ M4b Distinct-2)               phương án nhiễu đa dạng   lớp E (+ A)
  M5  Longest-Key Rate           (+ M5b Shortest-Key, M5c χ²)     không lộ qua độ dài       lớp A
  M6  Misconception Coverage                                      chẩn đoán được (riêng V3) lớp A (cần nhãn)
"""
from eval.quality import stats
from eval.quality.common import distractors, key_text, syllables, words

UNCLEAR = "khong_ro"

# mã, tên chuẩn, tên tiếng Việt, cột per-item, lớp cần, mục tiêu (hiển thị), luật đạt
CORE = [
    ("M1", "Open-book Solver Accuracy", "Giải đúng khi có ngữ cảnh", "S8_open_book", "S", "≥ 0,95", ("ge", 0.95)),
    ("M1b", "Ambiguity Rate", "Câu có ≥ 2 đáp án đúng (giám khảo)", "J2_multi_correct", "J", "≤ 0,05", ("le", 0.05)),
    ("M2", "Choices-only Accuracy", "Đoán đúng khi chỉ xem 4 phương án", "S6_options_only", "S", "≈ 0,25 (p ≥ 0,05)",
     ("chance", 0.25)),
    ("M3", "Semantic Plausibility Rate", "Phương án nhiễu có cos(d, key) trong dải [a, b]", "E2_in_band", "E",
     "≥ 0,70", ("ge", 0.70)),
    ("M3b", "Off-topic Rate", "Phương án nhiễu lạc đề (cos(d, slide) < τ)", "E3_off_topic", "E", "≤ 0,05",
     ("le", 0.05)),
    ("M4", "Near-duplicate Rate", "Câu có cặp phương án nhiễu cos > 0,9", "E4_dup_options", "E", "≤ 0,10",
     ("le", 0.10)),
    ("M4b", "Distinct-2", "Tỉ lệ bigram âm tiết khác nhau trong 3 phương án nhiễu", "C_distinct2", "A", "cao", None),
    ("M5", "Longest-Key Rate", "Đáp án đúng là phương án dài nhất", "A1_key_longest", "A", "≈ 0,25 (p ≥ 0,05)",
     ("chance", 0.25)),
    ("M5b", "Shortest-Key Rate", "Đáp án đúng là phương án ngắn nhất", "A1b_key_shortest", "A", "≈ 0,25 (p ≥ 0,05)",
     ("chance", 0.25)),
    ("M6", "Misconception Coverage", "Bộ 3 phủ ≥ 2 loại hiểu nhầm (nhãn LLM, chỉ V3)", "C_coverage", "A", "≥ 0,80",
     ("ge", 0.80)),
]
COLUMNS = {
    "C_distinct2": ("Distinct-2 của 3 phương án nhiễu", "M4b", "cao"),
    "C_key_len_rank": ("Hạng độ dài của đáp án đúng (0 = ngắn nhất … 3 = dài nhất)", "M5c", "≈ 1,5"),
    "C_coverage": ("Bộ 3 phủ ≥ 2 loại hiểu nhầm (nhãn LLM)", "M6", "≥ 0,80"),
}


def distinct_n(texts: list[str], n: int = 2) -> float | None:
    grams = [tuple(t[i:i + n]) for s in texts for t in [syllables(s)] for i in range(len(t) - n + 1)]
    return len(set(grams)) / len(grams) if grams else None


def per_item(item: dict) -> dict:
    lens = [words(key_text(item)), *[words(d) for d in distractors(item)]]
    k = lens[0]
    rank = sum(x < k for x in lens[1:]) + 0.5 * sum(x == k for x in lens[1:])   # hoà độ dài: lấy hạng giữa
    types = list((item.get("error_types") or {}).values())
    # Không có nhãn nào (V1, V2: không sinh theo hiểu nhầm) → không áp dụng, không tính là 0
    coverage = float(len({t for t in types if t and t != UNCLEAR}) >= 2) if any(types) else None
    return {"C_distinct2": distinct_n(distractors(item)), "C_key_len_rank": rank, "C_coverage": coverage}


def length_rank_test(items: list[dict]) -> dict:
    """M5c: hạng độ dài của đáp án đúng có phân bố đều trên 4 hạng không (χ², 3 bậc tự do).
    Hoà độ dài với k phương án khác: chia đều 1 câu cho các hạng trong khoảng hoà."""
    counts = [0.0] * 4
    for it in items:
        k = words(key_text(it))
        others = [words(d) for d in distractors(it)]
        lo = sum(x < k for x in others)
        hi = lo + sum(x == k for x in others)
        for r in range(lo, hi + 1):
            counts[r] += 1 / (hi - lo + 1)
    obs = [round(c) for c in counts]
    stat, p = stats.chi2_uniform(obs) if sum(obs) else (None, None)
    return {"M5c_rank_counts": obs, "M5c_chi2": stat, "M5c_p": p}


def _verdict(rule, value, p) -> str:
    if rule is None or value is None:
        return ""
    kind, x = rule
    if kind == "ge":
        return "✅" if value >= x else "❌"
    if kind == "le":
        return "✅" if value <= x else "❌"
    if kind == "chance":
        return "" if p is None else ("✅" if p >= 0.05 else "❌")
    return ""


def table(per_version: dict, items: dict, base: str, layers: list[str], cfg: dict, yields: list[dict]) -> tuple:
    """Trả (các dòng csv, đoạn markdown)."""
    order = (base, "V1", "V2", "V3", *sorted(v for v in per_version if v.startswith("LLM-")))
    versions = list(dict.fromkeys(v for v in order if v in per_version)) or list(per_version)
    target = "V3" if "V3" in per_version else (versions[-1] if len(versions) > 1 else None)
    rows, md = [], []
    rank = {v: length_rank_test(items[v]) for v in per_version}
    for code, name, vi, col, layer, target_txt, rule in CORE:
        for v in per_version:
            vals = [r.get(col) for r in per_version[v]]
            n = sum(x is not None for x in vals)
            m = stats.mean(vals)
            lo, hi = stats.bootstrap_ci(per_version[v], col, cfg["bootstrap"], cfg["seed"])
            p = None
            if rule and rule[0] == "chance" and n:
                p = stats.binom_two_sided(round(sum(x for x in vals if x is not None)), n, rule[1])
            d = (None, None, None, 0)
            if v != base and base in per_version:
                d = stats.bootstrap_diff(per_version[base], per_version[v], col, cfg["bootstrap"], cfg["seed"])
            rows.append({"code": code, "metric": name, "metric_vi": vi, "column": col, "layer": layer,
                         "version": v, "n": n, "value": m, "ci_lo": lo, "ci_hi": hi, "p_vs_chance": p,
                         "diff_vs_base": d[0], "diff_ci_lo": d[1], "diff_ci_hi": d[2], "target": target_txt,
                         "verdict": _verdict(rule, m, p)})
    get = {(r["code"], r["version"]): r for r in rows}

    def cell(code, v):
        r = get.get((code, v))
        if not r or r["value"] is None:
            if code == "M6" and not any(any((it.get("error_types") or {}).values()) for it in items.get(v, [])):
                return "không áp dụng"
            layer = next(c[4] for c in CORE if c[0] == code)
            return "chưa có" if layer in layers else f"chưa chạy lớp {layer}"
        txt = f"{r['value']:.3f} [{r['ci_lo']:.2f}; {r['ci_hi']:.2f}]"
        if r["p_vs_chance"] is not None:
            txt += f" p={r['p_vs_chance']:.3f}"
        return f"{txt} {r['verdict']}".strip()

    md += ["## Chỉ số chính (bộ đánh giá tự động)", "",
           "Định nghĩa, công thức và lý do chọn: `docs/bo-danh-gia.md`. Giá trị [CI 95% bootstrap theo chunk]; "
           "✅/❌ theo ngưỡng ở cột Mục tiêu; với mục tiêu ≈ 0,25, p là kiểm định nhị thức hai phía so với 0,25 "
           "(p ≥ 0,05 nghĩa là không phân biệt được với đoán ngẫu nhiên → đạt).", ""]
    head = " | ".join(versions)
    diff_head = f" | Hiệu {target}−{base} (CI 95%)" if target and base in per_version else ""
    md += [f"| Mã | Độ đo | Ý nghĩa | {head}{diff_head} | Mục tiêu |",
           "|---|---|---|" + "---|" * len(versions) + ("---|" if diff_head else "") + "---|"]
    for code, name, vi, *_rest in CORE:
        target_txt = _rest[2]
        dcell = ""
        if diff_head:
            r = get.get((code, target))
            if r and r["diff_vs_base"] is not None:
                sig = r["diff_ci_lo"] > 0 or r["diff_ci_hi"] < 0
                dcell = f" | {r['diff_vs_base']:+.3f} [{r['diff_ci_lo']:+.2f}; {r['diff_ci_hi']:+.2f}]{' *' if sig else ''}"
            else:
                dcell = " | "
        md.append(f"| {code} | **{name}** | {vi} | " + " | ".join(cell(code, v) for v in versions)
                  + f"{dcell} | {target_txt} |")
    md += ["", "| Mã | Độ đo | " + head + " | Mục tiêu |", "|---|---|" + "---|" * len(versions) + "---|",
           "| M5c | Key-length Rank Uniformity (χ², 3 bậc tự do): số câu có đáp án đúng ở hạng độ dài 0/1/2/3 | "
           + " | ".join(f"{rank[v]['M5c_rank_counts']} p={rank[v]['M5c_p']}" for v in versions) + " | p ≥ 0,05 |"]
    if yields:
        ymap = {y["version"]: y for y in yields}
        md.append("| Y | Generation Yield: câu đạt / hạt giống | "
                  + " | ".join(f"{ymap[v]['n_ok']}/{ymap[v]['n_seeds']}" if v in ymap else "" for v in versions)
                  + " | cao |")
    md += ["", "`*` = CI 95% của hiệu không chứa 0. M6 chỉ có ở phiên bản sinh theo hiểu nhầm (V3) và dùng nhãn do "
           "LLM gắn: chỉ mô tả, độ tin cậy của nhãn đo ở đánh giá người (G3).", ""]
    for v in per_version:
        rows.append({"code": "M5c", "metric": "Key-length Rank Uniformity", "version": v,
                     "value": rank[v]["M5c_p"], "metric_vi": str(rank[v]["M5c_rank_counts"]),
                     "target": "p ≥ 0,05", "verdict": _verdict(("ge", 0.05), rank[v]["M5c_p"], None)})
    return rows, "\n".join(md)
