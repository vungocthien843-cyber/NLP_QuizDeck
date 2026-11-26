"""Phân tích phiếu chấm người (kế hoạch v3, G2 + G3). Chạy SAU khi 2 người đã điền xong phiếu.

G2  - Độ đồng thuận giữa 2 người: Cohen's kappa (tiêu chí 0/1), weighted kappa bậc hai (thang 1–5).
    - So sánh V1 với V3 theo cặp cùng hạt giống: điểm của mỗi câu = trung bình 2 người; hiệu V3 − V1,
      khoảng tin cậy 95% bootstrap theo cặp và kiểm định Wilcoxon dấu-hạng (hai phía).
G3  - Kappa người1–người2, người–LLM; độ chính xác của nhãn LLM trên các câu 2 người cùng nhãn (CI Wilson);
      ma trận nhầm lẫn.
Đọc phiếu Excel (Phieu_cham_<tên>.xlsx trong data/). Chỉ một người gửi lại: chế độ một người chấm (bỏ kappa giữa người).
Kết quả: eval/human_v3/results/bao_cao_nguoi.md (+ các file csv chi tiết).
Chạy: python -m eval.human_v3.phan_tich
"""
import math
import random
from collections import Counter, defaultdict
from statistics import mean

from eval.human_v3.common import (D_BINARY, D_SCALE, KEY_LABEL, KEY_Q, Q_BINARY, Q_SCALE, RATERS, RESULTS, UNCLEAR,
                                  rater_name, read_csv, workbook, write_csv)
from eval.human_v3.xlsx_io import SHEET, filled_any, read_kind

BOOT = 10000


class SheetError(SystemExit):
    pass


# ----------------------------------------------------------------------------- đọc phiếu
def parse(rows: list[dict], id_col: str, binary: tuple, scale: tuple, name: str) -> dict[str, dict[str, int]]:
    out, bad = {}, []
    for r in rows:
        s = {}
        for col, allowed in [(c, {0, 1}) for c in binary] + [(c, {1, 2, 3, 4, 5}) for c in scale]:
            v = (r.get(col) or "").strip().replace(",", ".")
            try:
                f = float(v)
                ok = f.is_integer() and int(f) in allowed
            except ValueError:
                ok = False
            if ok:
                s[col] = int(float(v))
            else:
                bad.append(f"{r[id_col]}, cột {col}: {v!r}")
        out[r[id_col]] = s
    if bad:
        raise SheetError(f"{name} còn {len(bad)} ô thiếu hoặc sai (chỉ được {{0,1}} hoặc 1–5):\n  " + "\n  ".join(bad[:25]))
    return out


def valid_labels() -> set[str]:
    from app.prompts import misconception_types
    return set(misconception_types()) | {UNCLEAR}


def parse_labels(rows: list[dict], name: str, codes: set[str]) -> dict[str, str]:
    out, bad = {}, []
    for r in rows:
        v = (r.get("nhan") or "").strip().lower().replace(" ", "_")
        if v in codes:
            out[r["ma_nhan"]] = v
        else:
            bad.append(f"{r['ma_nhan']}: {r.get('nhan')!r}")
    if bad:
        raise SheetError(f"{name} còn {len(bad)} nhãn thiếu hoặc không đúng mã:\n  " + "\n  ".join(bad[:25])
                         + "\nMã hợp lệ: " + ", ".join(sorted(codes)))
    return out


def available_raters(kind: str) -> list[str]:
    """Người đã điền ít nhất một ô ở phiếu này (phiếu trắng chưa gửi lại thì bỏ qua)."""
    return [r for r in RATERS if filled_any(workbook(r), kind)]


def rows_of(r: str, kind: str) -> list[dict]:
    return read_kind(workbook(r), kind)


def where(r: str, kind: str) -> str:
    return f"{workbook(r).name} › {SHEET[kind]}"


# ----------------------------------------------------------------------------- thống kê
def kappa(x: list, y: list, weights: str | None = None) -> float | None:
    from sklearn.metrics import cohen_kappa_score
    if len(set(x) | set(y)) < 2:          # cả hai cho cùng một giá trị ở mọi câu: kappa không xác định
        return None
    return float(cohen_kappa_score(x, y, weights=weights))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def paired(a: list[float], b: list[float], rng: random.Random) -> dict:
    """a = V1, b = V3 (cùng thứ tự cặp). Hiệu b − a, CI bootstrap theo cặp, Wilcoxon hai phía."""
    from scipy.stats import wilcoxon
    d = [y - x for x, y in zip(a, b, strict=True)]
    n = len(d)
    boots = sorted(mean(d[rng.randrange(n)] for _ in range(n)) for _ in range(BOOT))
    if any(d):
        p = float(wilcoxon(d, zero_method="wilcox", alternative="two-sided").pvalue)
    else:
        p = 1.0
    return {"n_cap": n, "V1": mean(a), "V3": mean(b), "hieu": mean(d),
            "ci_thap": boots[int(0.025 * BOOT)], "ci_cao": boots[int(0.975 * BOOT) - 1], "p": p,
            "V3_tot_hon": sum(x > 0 for x in d), "bang_nhau": sum(x == 0 for x in d), "V1_tot_hon": sum(x < 0 for x in d)}


def agreement(sheets: dict[str, dict], cols_bin: tuple, cols_scale: tuple) -> list[dict]:
    a, b = (sheets[r] for r in RATERS)
    ids = sorted(set(a) & set(b))
    rows = []
    for c in (*cols_bin, *cols_scale):
        x, y = [a[i][c] for i in ids], [b[i][c] for i in ids]
        k = kappa(x, y, "quadratic" if c in cols_scale else None)
        rows.append({"tieu_chi": c, "loai_kappa": "weighted bậc hai" if c in cols_scale else "Cohen",
                     "ty_le_giong": round(sum(i == j for i, j in zip(x, y, strict=True)) / len(ids), 3),
                     "kappa": None if k is None else round(k, 3), "n": len(ids)})
    return rows


def fmt_k(k) -> str:
    return "—" if k is None else f"{k:.3f}"


def read_kappa(k) -> str:
    if k is None:
        return "không xác định"
    return ("kém" if k < 0.2 else "yếu" if k < 0.4 else "trung bình" if k < 0.6 else "khá" if k < 0.8 else "rất tốt")


# ----------------------------------------------------------------------------- G2
def g2(rng: random.Random, md: list[str]) -> None:
    raters = available_raters("cau_hoi")
    if not raters or not KEY_Q.exists():
        md.append("## G2: chưa có phiếu câu hỏi. Chạy tao_phieu và chờ người chấm điền xong.\n")
        return
    key = {r["ma_cau"]: r for r in read_csv(KEY_Q)}
    qs = {r: parse(rows_of(r, "cau_hoi"), "ma_cau", Q_BINARY, Q_SCALE, where(r, "cau_hoi"))
          for r in raters}
    ds_raw = {r: rows_of(r, "dap_an_nhieu") for r in raters if filled_any(workbook(r), "dap_an_nhieu")}
    ds = {r: parse(rows, "ma_pa", D_BINARY, D_SCALE, where(r, "dap_an_nhieu")) for r, rows in ds_raw.items()}
    pa_to_q = {row["ma_pa"]: row["ma_cau"] for rows in ds_raw.values() for row in rows}

    md.append(f"## G2: chất lượng câu hỏi V1 và V3 (người chấm: {', '.join(rater_name(r) for r in raters)})\n")
    if len(raters) == 2:
        ag = agreement(qs, Q_BINARY, Q_SCALE)
        if len(ds) == 2:
            ag += agreement(ds, D_BINARY, D_SCALE)
        write_csv(RESULTS / "g2_dong_thuan.csv", ag)
        md.append("### Độ đồng thuận giữa 2 người chấm\n")
        md.append("| Tiêu chí | Kappa | Đánh giá | Tỉ lệ giống | n |\n|---|---|---|---|---|")
        md += [f"| `{r['tieu_chi']}` ({r['loai_kappa']}) | {r['kappa']} | {read_kappa(r['kappa'])} | "
               f"{r['ty_le_giong']:.0%} | {r['n']} |" for r in ag]
        md.append("")
    else:
        md.append("_Chế độ một người chấm: không tính kappa giữa người._\n")

    # điểm mỗi câu = trung bình các người chấm
    metric: dict[str, dict[str, float]] = defaultdict(dict)
    for code in key:
        per = [qs[r][code] for r in raters if code in qs[r]]
        if not per:
            continue
        metric[code]["dat_ca_3_tieu_chi"] = mean(float(all(p[c] == 1 for c in Q_BINARY)) for p in per)
        for c in (*Q_BINARY, *Q_SCALE):
            metric[code][c] = mean(p[c] for p in per)
    if ds:
        by_q: dict[str, list[dict]] = defaultdict(list)
        for r, sc in ds.items():
            for pa, s in sc.items():
                by_q[pa_to_q[pa]].append(s)
        for code, ss in by_q.items():
            metric[code]["pa_chac_chan_sai"] = mean(s["chac_chan_sai"] for s in ss)
            metric[code]["pa_hop_ly"] = mean(s["hop_ly"] for s in ss)
            metric[code]["pa_hop_ly_tu_4"] = mean(float(s["hop_ly"] >= 4) for s in ss)
            metric[code]["pa_the_hien_hieu_nham"] = mean(s["the_hien_hieu_nham"] for s in ss)

    pairs = defaultdict(dict)
    for code, k in key.items():
        if code in metric:
            pairs[k["chunk_id"]][k["phien_ban"]] = metric[code]
    full = [p for p in pairs.values() if {"V1", "V3"} <= set(p)]
    names = {"dat_ca_3_tieu_chi": "Câu đạt (cả 3 tiêu chí 0/1)", "dung_kien_thuc": "Đúng kiến thức",
             "mot_dap_an_dung": "Một đáp án đúng", "tu_dung_duoc": "Tự đứng được", "ro_rang": "Rõ ràng (1–5)",
             "phuong_an_sai_hop_ly": "Phương án sai hợp lý, cả câu (1–5)",
             "pa_chac_chan_sai": "PA sai: chắc chắn sai", "pa_hop_ly": "PA sai: hợp lý (1–5)",
             "pa_hop_ly_tu_4": "PA sai: tỉ lệ hợp lý ≥ 4", "pa_the_hien_hieu_nham": "PA sai: thể hiện hiểu nhầm"}
    rows = []
    for m, label in names.items():
        if not all(m in p["V1"] and m in p["V3"] for p in full):
            continue
        res = paired([p["V1"][m] for p in full], [p["V3"][m] for p in full], rng)
        rows.append({"chi_so": m, "ten": label, **{k: round(v, 4) if isinstance(v, float) else v
                                                   for k, v in res.items()}})
    write_csv(RESULTS / "g2_so_sanh.csv", rows)
    md.append(f"### So sánh theo cặp cùng hạt giống ({len(full)} cặp)\n")
    md.append("Điểm mỗi câu là trung bình của các người chấm. Hiệu = V3 − V1; khoảng tin cậy 95% bootstrap "
              f"({BOOT} lần); p theo kiểm định Wilcoxon dấu-hạng hai phía.\n")
    md.append("| Chỉ số | V1 | V3 | Hiệu | CI 95% | p | V3 hơn / bằng / V1 hơn |\n|---|---|---|---|---|---|---|")
    for r in rows:
        star = " **" if r["p"] < 0.05 else ""
        md.append(f"| {r['ten']} | {r['V1']:.3f} | {r['V3']:.3f} | {r['hieu']:+.3f}{star} | "
                  f"[{r['ci_thap']:+.3f}; {r['ci_cao']:+.3f}] | {r['p']:.4f} | "
                  f"{r['V3_tot_hon']} / {r['bang_nhau']} / {r['V1_tot_hon']} |")
    md.append("\n`**` = khác biệt có ý nghĩa ở mức 0,05. Đây là nhiều phép kiểm định trên cùng mẫu; nếu cần chặt "
              "hơn, dùng ngưỡng Bonferroni 0,05 / số chỉ số.\n")


# ----------------------------------------------------------------------------- G3
def g3(md: list[str]) -> None:
    raters = available_raters("nhan")
    if not raters or not KEY_LABEL.exists():
        md.append("## G3: chưa có phiếu gán nhãn.\n")
        return
    codes = valid_labels()
    llm = {r["ma_nhan"]: r["nhan_llm"] for r in read_csv(KEY_LABEL)}
    hum = {r: parse_labels(rows_of(r, "nhan"), where(r, "nhan"), codes) for r in raters}
    ids = sorted(set(llm).intersection(*(set(h) for h in hum.values())))
    md.append(f"## G3: nhãn hiểu nhầm của LLM so với người ({len(ids)} phương án sai)\n")
    rows = []
    for r in raters:
        x, y = [hum[r][i] for i in ids], [llm[i] for i in ids]
        rows.append({"cap": f"{rater_name(r)} – LLM", "kappa": kappa(x, y),
                     "ty_le_giong": sum(a == b for a, b in zip(x, y, strict=True)) / len(ids)})
    if len(raters) == 2:
        x, y = [hum[RATERS[0]][i] for i in ids], [hum[RATERS[1]][i] for i in ids]
        rows.insert(0, {"cap": f"{rater_name(RATERS[0])} – {rater_name(RATERS[1])} (giữa 2 người)", "kappa": kappa(x, y),
                        "ty_le_giong": sum(a == b for a, b in zip(x, y, strict=True)) / len(ids)})
    md.append("| Cặp | Cohen's kappa | Đánh giá | Tỉ lệ giống |\n|---|---|---|---|")
    md += [f"| {r['cap']} | {fmt_k(r['kappa'])} | "
           f"{read_kappa(r['kappa'])} | {r['ty_le_giong']:.0%} |" for r in rows]
    md.append("")

    if len(raters) == 2:
        agreed = [i for i in ids if hum[RATERS[0]][i] == hum[RATERS[1]][i]]
        hit = sum(llm[i] == hum[RATERS[0]][i] for i in agreed)
        lo, hi = wilson(hit, len(agreed))
        loose = sum(llm[i] in {hum[r][i] for r in raters} for i in ids)
        md.append(f"- **Độ chính xác nhãn LLM trên {len(agreed)} phương án hai người cùng nhãn:** "
                  f"{hit}/{len(agreed)} = {hit / max(len(agreed), 1):.0%} (CI 95% Wilson [{lo:.0%}; {hi:.0%}]).")
        md.append(f"- Nới lỏng (LLM trùng ít nhất một người): {loose}/{len(ids)} = {loose / len(ids):.0%}.")
        ref = {i: hum[RATERS[0]][i] for i in agreed}
    else:
        ref = {i: hum[raters[0]][i] for i in ids}
        hit = sum(llm[i] == ref[i] for i in ids)
        md.append(f"- Độ chính xác nhãn LLM so với {rater_name(raters[0])}: {hit}/{len(ids)} = {hit / len(ids):.0%}.")
    summary = [{"chi_so": f"kappa: {r['cap']}", "gia_tri": r["kappa"], "ty_le_giong": r["ty_le_giong"]} for r in rows]
    if len(raters) == 2:
        summary.append({"chi_so": "accuracy_llm_tren_nhan_dong_thuan", "gia_tri": hit / max(len(agreed), 1),
                        "n": len(agreed), "ci_lo": lo, "ci_hi": hi})
    else:
        summary.append({"chi_so": "accuracy_llm_so_voi_1_nguoi", "gia_tri": hit / len(ids), "n": len(ids)})
    write_csv(RESULTS / "g3_tong_hop.csv", summary, list(dict.fromkeys(k for r in summary for k in r)))
    unclear_h = sum(v == UNCLEAR for v in ref.values())
    md.append(f"- Người cho `{UNCLEAR}`: {unclear_h}/{len(ref)} phương án (phương án không thể hiện loại "
              "hiểu nhầm nào trong bảng).\n")

    labels = sorted(codes)
    conf = Counter((ref[i], llm[i]) for i in ref)
    write_csv(RESULTS / "g3_ma_tran_nham_lan.csv",
              [{"nguoi \\ llm": a, **{b: conf.get((a, b), 0) for b in labels}} for a in labels])
    per = []
    for lb in labels:
        tp = conf.get((lb, lb), 0)
        pred = sum(v for (a, b), v in conf.items() if b == lb)
        true = sum(v for (a, b), v in conf.items() if a == lb)
        if pred or true:
            per.append({"nhan": lb, "nguoi": true, "llm": pred,
                        "precision": round(tp / pred, 3) if pred else None,
                        "recall": round(tp / true, 3) if true else None})
    write_csv(RESULTS / "g3_theo_nhan.csv", per)
    md.append("| Nhãn | Người gán | LLM gán | Precision | Recall |\n|---|---|---|---|---|")
    md += [f"| `{p['nhan']}` | {p['nguoi']} | {p['llm']} | {p['precision']} | {p['recall']} |" for p in per]
    md.append("\nMa trận nhầm lẫn đầy đủ: `g3_ma_tran_nham_lan.csv` (hàng = người, cột = LLM).\n")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    md = ["# Báo cáo đánh giá người (v3: G2 và G3)\n",
          "Mức kappa: < 0,2 kém · 0,2–0,4 yếu · 0,4–0,6 trung bình · 0,6–0,8 khá · ≥ 0,8 rất tốt (Landis & Koch).\n"]
    g2(rng, md)
    g3(md)
    out = RESULTS / "bao_cao_nguoi.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
