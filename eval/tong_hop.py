"""BÁO CÁO ĐÁNH GIÁ TỔNG HỢP: gom kết quả 3 tầng của bộ đánh giá vào một file (docs/bo-danh-gia.md).

  Tầng 1  tự động        eval/quality/results/<thời điểm>/core.csv   (run_eval: A, E, S, J)
  Tầng 2  người chấm     eval/human_v3/results/g2_*.csv, g3_tong_hop.csv
  Tầng 3  sinh viên      eval/student/results/g4_tong_hop.csv, theo_sinh_vien.csv

Tầng 1: với mỗi độ đo lấy lần chạy MỚI NHẤT có giá trị (lớp A+E và lớp S+J thường chạy riêng). Tầng nào chưa có
dữ liệu thì ghi "chưa có" kèm việc cần làm. Kết quả: eval/BAO_CAO_DANH_GIA.md.
  python -m eval.tong_hop
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "BAO_CAO_DANH_GIA.md"
QUALITY = ROOT / "quality" / "results"
HUMAN = ROOT / "human_v3" / "results"
STUDENT = ROOT / "student" / "results"
MAIN_VERSIONS = ("V1", "V2", "V3", "LLM-GPT", "LLM-Gemini")   # LLM-*: đối chứng LLM trực tiếp (eval/baseline_llm.py)
ABLATION = ("V2-random", "V2-top3", "V2-no-delta", "V2", "V3-chi-ViT5", "V3-chi-LLM", "V3")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(x) -> float | None:
    try:
        return None if x in (None, "", "None") else float(x)
    except ValueError:
        return None


def f3(x, d=3) -> str:
    x = num(x)
    return "—" if x is None else f"{x:.{d}f}"


# ----------------------------------------------------------------------------- tầng 1
def _data_of(core_csv: Path) -> str:
    try:
        return Path(json.loads((core_csv.parent / "run.json").read_text(encoding="utf-8"))["data"]).name
    except (OSError, ValueError, KeyError):
        return ""


def tier1(data: str | None = None) -> tuple[list[str], dict]:
    runs = sorted((p for p in QUALITY.glob("*/core.csv")), key=lambda p: p.parent.name, reverse=True)
    data = data or (_data_of(runs[0]) if runs else None)        # mặc định: bộ dữ liệu của lần chạy mới nhất
    runs = [p for p in runs if _data_of(p) == data]           # KHÔNG trộn kết quả của hai bộ dữ liệu khác nhau
    md = [f"## Tầng 1: đánh giá tự động (bộ dữ liệu `{data}`, không cần người)", ""]
    if not runs:
        md += ["_Chưa có lần chạy nào có bảng chỉ số chính. Chạy `scripts\\1_sinh_doi_chung_llm.bat` (lớp A + E, miễn phí) "
               "rồi `scripts\\2_cham_openai.bat` (lớp S + J)._", ""]
        return md, {}
    best: dict = {}                       # (mã, phiên bản) → dòng của lần chạy mới nhất có giá trị
    meta: dict = {}
    for path in runs:
        run = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
        for r in read_csv(path):
            key = (r["code"], r["version"])
            if key not in best and num(r.get("value")) is not None:
                best[key] = {**r, "_run": path.parent.name, "_sample": run.get("sample"),
                             "_llm": (run.get("llm_eval") or {})}
                meta.setdefault(path.parent.name, run)
    codes = list(dict.fromkeys(r["code"] for p in runs for r in read_csv(p)))
    names = {r["code"]: (r["metric"], r.get("target", "")) for p in runs for r in read_csv(p)}
    versions = [v for v in MAIN_VERSIONS if any(k[1] == v for k in best)]
    md += ["| Mã | Độ đo | " + " | ".join(versions) + " | Hiệu V3−mốc | Mục tiêu | Nguồn |",
           "|---|---|" + "---|" * len(versions) + "---|---|---|"]
    for c in codes:
        if c == "M5c":
            continue
        name, target = names[c]
        cells, src = [], set()
        for v in versions:
            r = best.get((c, v))
            if not r:
                cells.append("không áp dụng" if c == "M6" and (v in ("V1", "V2") or v.startswith("LLM-")) else "chưa có")
                continue
            p = f" (p={f3(r.get('p_vs_chance'))})" if num(r.get("p_vs_chance")) is not None else ""
            cells.append(f"{f3(r['value'])}{p} {r.get('verdict', '')}".strip())
            src.add(r["_run"] + (f", mẫu {r['_sample']}" if r.get("_sample") else ""))
        d = best.get((c, "V3"))
        dcell = ""
        if d and num(d.get("diff_vs_base")) is not None:
            sig = num(d["diff_ci_lo"]) > 0 or num(d["diff_ci_hi"]) < 0
            mb = meta.get(d["_run"], {}).get("base") or "V1"
            dcell = f"{num(d['diff_vs_base']):+.3f}{' *' if sig else ''} (so {mb})"
        md.append(f"| {c} | **{name}** | " + " | ".join(cells) + f" | {dcell} | {target} | {', '.join(sorted(src))} |")
    m5c = [best.get(("M5c", v)) for v in versions]
    if any(m5c):
        md.append("| M5c | **Key-length Rank Uniformity** (χ² p; số câu theo hạng 0–3) | "
                  + " | ".join(f"p={f3(r['value'])} {r['metric_vi']} {r.get('verdict', '')}" if r else "chưa có"
                               for r in m5c) + " |  | p ≥ 0,05 | |")
    llm = next((r["_llm"] for r in best.values() if r.get("_llm")), {})
    md += ["", "LLM-GPT / LLM-Gemini: đối chứng LLM trực tiếp — cùng slide, câu hỏi, đáp án đúng với V3, chỉ một lời gọi "
           "sinh 3 phương án nhiễu (không 7 kiểu hiểu nhầm, không lọc, không xếp hạng).",
           "`*` = CI 95% của hiệu không chứa 0. Chi tiết, CI và kiểm định: report.md của lần chạy ở cột Nguồn.",
           *([f"Lớp S/J: giám khảo `{llm.get('judge')}`, người giải {llm.get('solvers')}."] if llm else []), ""]
    # ablation
    abl = [v for v in ABLATION if any(k[1] == v for k in best)]
    if len([v for v in abl if v not in MAIN_VERSIONS]) >= 1:
        md += ["### Ablation (cùng kho ứng viên, chọn lại không sinh lại)", "",
               "| Độ đo | " + " | ".join(abl) + " |", "|---|" + "---|" * len(abl)]
        for c in ("M3", "M4", "M4b", "M5", "M5b", "M6"):
            if any(best.get((c, v)) for v in abl):
                md.append(f"| {c} {names.get(c, ('', ''))[0]} | "
                          + " | ".join(f3(best[(c, v)]["value"]) if (c, v) in best else "—" for v in abl) + " |")
        md += ["", "V2-random / V2-top3 / V2-no-delta: cách chọn bộ 3 (ngẫu nhiên, 3 điểm cao nhất, entropy không δ). "
               "V3-chi-ViT5 / V3-chi-LLM: chỉ dùng ứng viên của một nguồn sinh.", ""]
    return md, best


# ----------------------------------------------------------------------------- tầng 2
def tier2() -> list[str]:
    md = ["## Tầng 2: người chấm (G2 chất lượng câu, G3 nhãn hiểu nhầm)", ""]
    g2 = {r["chi_so"]: r for r in read_csv(HUMAN / "g2_so_sanh.csv")}
    ag = {r["tieu_chi"]: r for r in read_csv(HUMAN / "g2_dong_thuan.csv")}
    g3 = read_csv(HUMAN / "g3_tong_hop.csv")
    if not (g2 or g3):
        return md + ["_Chưa có. Phiếu đã gửi cho 2 người chấm; nhận lại thì chép vào `eval\\human_v3\\data` và chạy "
                     "`scripts\\6_phan_tich_phieu_nguoi.bat`._", ""]
    md += ["| Mã | Độ đo | V1 | V3 | Hiệu (CI 95%) | p (Wilcoxon) | κ giữa 2 người | Mục tiêu |",
           "|---|---|---|---|---|---|---|---|"]
    spec = [("H1", "Item Validity Rate (câu đạt cả 3 tiêu chí)", "dat_ca_3_tieu_chi", "mot_dap_an_dung", "≥ 0,80"),
            ("H2", "Distractor Plausibility (1–5, từng phương án)", "pa_hop_ly", "hop_ly", "≥ 3,5"),
            ("H2b", "Distractor Plausibility (1–5, cả câu)", "phuong_an_sai_hop_ly", "phuong_an_sai_hop_ly", "≥ 3,5"),
            ("H3", "Misconception Expression Rate (PA thể hiện hiểu nhầm)", "pa_the_hien_hieu_nham",
             "the_hien_hieu_nham", "V3 > V1"),
            ("H4", "Non-ambiguity (chỉ một đáp án đúng)", "mot_dap_an_dung", "mot_dap_an_dung", "≥ 0,90")]
    for code, name, key, kcol, target in spec:
        r = g2.get(key)
        if not r:
            continue
        sig = num(r["ci_thap"]) > 0 or num(r["ci_cao"]) < 0
        md.append(f"| {code} | **{name}** | {f3(r['V1'])} | {f3(r['V3'])} | {num(r['hieu']):+.3f} "
                  f"[{f3(r['ci_thap'], 2)}; {f3(r['ci_cao'], 2)}]{' *' if sig else ''} | {f3(r['p'], 4)} | "
                  f"{f3((ag.get(kcol) or {}).get('kappa'))} | {target} |")
    if g3:
        md += ["", "| Mã | Độ tin cậy của nhãn hiểu nhầm (G3) | Giá trị | Mục tiêu |", "|---|---|---|---|"]
        for r in g3:
            target = "≥ 0,4 và gần κ giữa 2 người" if r["chi_so"].startswith("kappa") else "cao"
            extra = (f" (n={r['n']}, CI [{f3(r.get('ci_lo'), 2)}; {f3(r.get('ci_hi'), 2)}])"
                     if r.get("n") else "")
            md.append(f"| H5 | {r['chi_so']} | {f3(r['gia_tri'])}{extra} | {target} |")
    return md + ["", "Chi tiết: `eval/human_v3/results/bao_cao_nguoi.md`.", ""]


# ----------------------------------------------------------------------------- tầng 3
def tier3() -> list[str]:
    md = ["## Tầng 3: sinh viên làm bài thật (G4 phân tích câu, G5 cá nhân hoá)", ""]
    g4 = read_csv(STUDENT / "g4_tong_hop.csv")
    stu = read_csv(STUDENT / "theo_sinh_vien.csv")
    if not (g4 or stu):
        return md + ["_Chưa có. Chạy `scripts\\7_thu_nghiem_sv_chuan_bi.bat`, tổ chức buổi thử nghiệm (kịch bản: "
                     "`eval\\student\\kich_ban_thu_nghiem.md`), rồi `scripts\\8_thu_nghiem_sv_phan_tich.bat`._", ""]
    names = {"p": ("Difficulty Index p", "0,3–0,8"), "D": ("Discrimination Index D (27%)", "≥ 0,3"),
             "r_pb": ("Point-biserial r_pb", "≥ 0,2"),
             "pa_khong_hoat_dong": ("Số phương án nhiễu không hoạt động / câu", "thấp")}
    md += ["| Mã | Độ đo | Số cặp | V1 | V3 | Hiệu (CI 95%) | Mục tiêu |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(x for x in g4 if x["chi_so"] in names):
        n, t = names[r["chi_so"]]
        md.append(f"| T{i + 1} | **{n}** | {r.get('n')} | {f3(r.get('V1'))} | {f3(r.get('V3'))} | "
                  f"{num(r['hieu']):+.3f} [{f3(r.get('lo'), 2)}; {f3(r.get('hi'), 2)}] | {t} |")
    nfd = [r for r in g4 if r["chi_so"].startswith("NFD%")]
    if nfd:
        md.append("| T5 | **NFD%** (phương án nhiễu được < 5% người chọn) | | "
                  + " | ".join(f3(next((r.get(v) for r in nfd if r.get(v)), None)) for v in ("V1", "V3"))
                  + " | | < 0,20 |")
    if stu:
        by = {g: [r for r in stu if r["nhom"] == g] for g in "AB"}
        gain = {g: [num(r["tien_bo"]) for r in xs if num(r["tien_bo"]) is not None] for g, xs in by.items()}
        md += ["", f"G5: {len(by['A'])} sinh viên luyện điểm yếu (A), {len(by['B'])} luyện đề thường (B). Tiến bộ Đề 2 − "
                   "Đề 1 trung bình: " + " · ".join(f"nhóm {g} {sum(x) / len(x):+.2f}" for g, x in gain.items() if x)
               + " (mô tả, mẫu nhỏ)."]
    return md + ["", "Chi tiết: `eval/student/results/bao_cao_sinh_vien.md`.", ""]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="tên thư mục dữ liệu của tầng 1, ví dụ data_nlp (mặc định: của lần chạy mới nhất)")
    a, _ = ap.parse_known_args()
    md1, best = tier1(Path(a.data).name if a.data else None)
    status = [
        ("Tầng 1 tự động", "✅ có" if best else "❌ chưa có",
         "lớp S/J đủ" if any(k[0] in ("M1", "M2") for k in best) else "thiếu lớp S/J (M1, M2)"),
        ("Tầng 2 người chấm", "✅ có" if (HUMAN / "g2_so_sanh.csv").exists() else "⏳ chờ phiếu", ""),
        ("Tầng 3 sinh viên", "✅ có" if (STUDENT / "g4_tong_hop.csv").exists() else "⏳ chưa thử nghiệm", ""),
    ]
    head = ["# BÁO CÁO ĐÁNH GIÁ HỆ THỐNG SINH CÂU HỎI TRẮC NGHIỆM", "",
            "Bộ đánh giá 3 tầng, định nghĩa từng độ đo: `docs/bo-danh-gia.md`. File này tạo tự động bởi "
            "`python -m eval.tong_hop` (`scripts\\3_bao_cao_tong_hop.bat`); chạy lại sau mỗi lần có kết quả mới.", "",
            "| Tầng | Trạng thái | Ghi chú |", "|---|---|---|", *[f"| {a} | {b} | {c} |" for a, b, c in status], ""]
    OUT.write_text("\n".join(head + md1 + tier2() + tier3()), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
