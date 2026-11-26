"""Tính kết quả phiếu chấm người (lớp B): điểm R1–R6 theo phiên bản, tỉ lệ quyết định R7, tỉ lệ J1/J2.

So sánh theo cặp: mỗi chunk có 1 câu mỗi phiên bản, nên hiệu được lấy mẫu lại theo chunk (bootstrap) và CI không
chứa 0 thì coi là khác biệt có ý nghĩa. Chỉ có một người chấm: không tính được độ đồng thuận giữa người chấm.

  python -m eval.quality.human_score [--sheet eval/quality/human/phieu_cham.csv]
Ra: eval/quality/human/ket_qua.csv và ket_qua.md
"""
import argparse
import csv
from pathlib import Path

from eval.quality import stats
from eval.quality.common import ROOT, load_cfg

HUMAN = ROOT / "human"
SCALE = {"R1_chinh_xac": "Chính xác", "R2_dung_duy_nhat": "Đúng duy nhất", "R3_trong_tam": "Trọng tâm",
         "R4_muc_nhan_thuc": "Mức nhận thức", "R5_nhieu_hop_ly": "Đáp án nhiễu hợp lý",
         "R6_khong_lo_dap_an": "Không lộ đáp án"}
BINARY = {"J1_dap_an_co_can_cu": "Đáp án được slide chứng minh", "J2_mot_dap_an_dung": "Đúng một đáp án đúng"}
DECISIONS = {"dung_ngay": "Dùng ngay", "sua_nhe": "Sửa nhẹ", "loai": "Loại"}


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse(rows: list[dict], key: dict) -> tuple[list[dict], list[str]]:
    out, problems = [], []
    for r in rows:
        code = r["ma_cau"]
        rec = {"ma_cau": code, **key[code]}
        for col in SCALE:
            v = (r.get(col) or "").strip()
            if v not in {"1", "2", "3", "4", "5"}:
                problems.append(f"{code} {col}={v!r}")
            rec[col] = float(v) if v in {"1", "2", "3", "4", "5"} else None
        for col in BINARY:
            v = (r.get(col) or "").strip()
            if v not in {"0", "1"}:
                problems.append(f"{code} {col}={v!r}")
            rec[col] = float(v) if v in {"0", "1"} else None
        d = (r.get("R7_quyet_dinh") or "").strip().lower()
        if d not in DECISIONS:
            problems.append(f"{code} R7_quyet_dinh={d!r}")
        for k in DECISIONS:
            rec[f"R7_{k}"] = (1.0 if d == k else 0.0) if d in DECISIONS else None
        out.append(rec)
    return out, problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", default=str(HUMAN / "phieu_cham.csv"))
    a = ap.parse_args()
    cfg = load_cfg()
    key = {r["ma_cau"]: {"version": r["version"], "chunk_id": r["chunk_id"], "item_id": r["item_id"]}
           for r in read(HUMAN / "khoa.csv")}
    rows, problems = parse(read(Path(a.sheet)), key)
    if problems:
        print(f"{len(problems)} ô trống hoặc sai định dạng (bỏ qua khi tính):\n  " + "\n  ".join(problems[:20]))
    versions = sorted({r["version"] for r in rows})
    labels = {**SCALE, **BINARY, **{f"R7_{k}": f"Tỉ lệ '{v}'" for k, v in DECISIONS.items()}}
    table = []
    for col, label in labels.items():
        row = {"metric": col, "label": label}
        for v in versions:
            sub = [r for r in rows if r["version"] == v]
            m = stats.mean([r[col] for r in sub])
            lo, hi = stats.bootstrap_ci(sub, col, cfg["bootstrap"], cfg["seed"])
            row[v] = m
            row[f"{v}_ci"] = (lo, hi)
        if len(versions) == 2:
            a_rows = [r for r in rows if r["version"] == versions[0]]
            b_rows = [r for r in rows if r["version"] == versions[1]]
            d, lo, hi, _ = stats.bootstrap_diff(a_rows, b_rows, col, cfg["bootstrap"], cfg["seed"])
            row["diff"], row["diff_ci"] = d, (lo, hi)
            row["significant"] = None if lo is None else (lo > 0 or hi < 0)
        table.append(row)

    f3 = lambda x: "" if x is None else f"{x:.2f}"  # noqa: E731
    with open(HUMAN / "ket_qua.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["metric", *versions, "diff", "diff_ci_lo", "diff_ci_hi", "significant"])
        for r in table:
            w.writerow([r["metric"], *[f3(r[v]) for v in versions], f3(r.get("diff")),
                        f3((r.get("diff_ci") or (None, None))[0]), f3((r.get("diff_ci") or (None, None))[1]),
                        r.get("significant")])
    lines = ["# Kết quả người chấm", "", f"{len(rows)} câu, {len(versions)} phiên bản, 1 người chấm.", "",
             "| Tiêu chí | " + " | ".join(versions) + (f" | Hiệu {versions[1]}−{versions[0]} (CI 95%)" if len(versions) == 2 else "") + " |",
             "|---|" + "---|" * (len(versions) + (len(versions) == 2))]
    for r in table:
        cells = [f"{f3(r[v])} [{f3(r[f'{v}_ci'][0])}, {f3(r[f'{v}_ci'][1])}]" for v in versions]
        if len(versions) == 2:
            lo, hi = r["diff_ci"]
            cells.append(f"{f3(r['diff'])} [{f3(lo)}, {f3(hi)}]{' *' if r['significant'] else ''}")
        lines.append(f"| {r['label']} | " + " | ".join(cells) + " |")
    lines += ["", "`*` = CI 95% của hiệu không chứa 0. R1–R6 thang 1–5; J1, J2, R7 là tỉ lệ.",
              "Hạn chế: một người chấm (không có kappa giữa người chấm); người chấm là sinh viên đã học môn."]
    (HUMAN / "ket_qua.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
