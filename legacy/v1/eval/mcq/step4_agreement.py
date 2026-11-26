"""Bước 4: đọc phiếu của 2 người, tính độ đồng thuận và chất lượng câu hỏi.

Chạy lần 1: tính kappa và tạo data/phieu_chot.csv, trong đó câu bất đồng để trống để 2 người thảo luận rồi điền.
Chạy lần 2 (sau khi điền xong): tính tỉ lệ đạt, precision, recall của bộ lọc.
Chạy: python -m eval.mcq.step4_agreement
"""
from sklearn.metrics import cohen_kappa_score

from eval.mcq.common import (
    BINARY_CRITERIA,
    RESULTS_DIR,
    SAMPLE_KEY,
    SCALE_CRITERIA,
    SHEET_FINAL,
    SHEET_RATER1,
    SHEET_RATER2,
    fail,
    load_questions,
    read_csv,
    wilson,
    write_csv,
)


def parse_sheet(rows: list[dict], name: str) -> dict[str, dict[str, int]]:
    """Đọc điểm của một phiếu; báo đúng ô bị thiếu hoặc sai để người chấm sửa."""
    parsed: dict[str, dict[str, int]] = {}
    problems: list[str] = []
    for row in rows:
        scores: dict[str, int] = {}
        for criterion, allowed in ((c, {0, 1}) for c in BINARY_CRITERIA):
            scores[criterion] = _score(row, criterion, allowed, problems)
        for criterion in SCALE_CRITERIA:
            scores[criterion] = _score(row, criterion, {1, 2, 3, 4, 5}, problems)
        parsed[row["ma_cau"]] = scores
    if problems:
        shown = "\n  ".join(problems[:20])
        fail(f"{name} còn {len(problems)} ô thiếu hoặc sai:\n  {shown}")
    return parsed


def _score(row: dict, criterion: str, allowed: set[int], problems: list[str]) -> int:
    value = (row.get(criterion) or "").strip()
    if value.isdigit() and int(value) in allowed:
        return int(value)
    problems.append(f"{row['ma_cau']}, cột {criterion}: {value!r}")
    return -1


def agreement_rows(a: dict[str, dict[str, int]], b: dict[str, dict[str, int]]) -> list[dict]:
    """Cohen's kappa cho tiêu chí đạt/lỗi, weighted kappa (quadratic) cho thang 1–5."""
    codes = sorted(a)
    rows = []
    for criterion in (*BINARY_CRITERIA, *SCALE_CRITERIA):
        x, y = [a[c][criterion] for c in codes], [b[c][criterion] for c in codes]
        weights = "quadratic" if criterion in SCALE_CRITERIA else None
        same = sum(i == j for i, j in zip(x, y, strict=True)) / len(codes)
        # Hai người cho cùng một giá trị ở mọi câu thì kappa không xác định (mẫu số bằng 0)
        kappa = None if len(set(x) | set(y)) < 2 else cohen_kappa_score(x, y, weights=weights)
        rows.append({"tieu_chi": criterion, "loai_kappa": "weighted" if weights else "cohen",
                     "kappa": "" if kappa is None else round(float(kappa), 3), "ti_le_giong_nhau": round(same, 3)})
    return rows


def build_final_sheet(a: dict[str, dict[str, int]], b: dict[str, dict[str, int]], sheet: list[dict]) -> list[dict]:
    """Câu hai người giống nhau thì điền sẵn; câu khác nhau để trống. Thang 1–5 lấy trung bình, không cần chốt."""
    rows = []
    for source in sheet:
        code = source["ma_cau"]
        row = {"ma_cau": code, "cau_hoi": source["cau_hoi"]}
        for criterion in BINARY_CRITERIA:
            same = a[code][criterion] == b[code][criterion]
            row[criterion] = a[code][criterion] if same else ""
            row[f"{criterion}_nguoi1"] = a[code][criterion]
            row[f"{criterion}_nguoi2"] = b[code][criterion]
        rows.append(row)
    return rows


def parse_final(rows: list[dict]) -> dict[str, bool] | None:
    """ma_cau → đạt (cả 4 tiêu chí đều bằng 1). Trả None nếu còn ô chưa chốt."""
    verdicts = {}
    for row in rows:
        values = [(row.get(c) or "").strip() for c in BINARY_CRITERIA]
        if any(v not in ("0", "1") for v in values):
            return None
        verdicts[row["ma_cau"]] = all(v == "1" for v in values)
    return verdicts


def filter_metrics(sampled_acc_pass: int, sampled_acc: int, sampled_rej_pass: int, sampled_rej: int,
                   population_acc: int, population_rej: int) -> dict:
    """Coi người chấm là chuẩn, "câu tốt" là lớp dương. Mẫu lấy dư câu rejected so với thực tế, nên recall
    phải quy về quy mô thật của từng nhóm, không tính thẳng trên mẫu."""
    precision = sampled_acc_pass / sampled_acc if sampled_acc else 0.0
    wrongly_rejected = sampled_rej_pass / sampled_rej if sampled_rej else 0.0
    good_kept = precision * population_acc
    good_lost = wrongly_rejected * population_rej
    recall = good_kept / (good_kept + good_lost) if good_kept + good_lost else 0.0
    return {"precision": precision, "recall": recall, "wrongly_rejected": wrongly_rejected}


def quality_rows(verdicts: dict[str, bool], key: list[dict], a: dict, b: dict, questions: list[dict]) -> list[dict]:
    rows: list[dict] = []

    def add(name: str, value: float | int, note: str = "") -> None:
        rows.append({"chi_so": name, "gia_tri": round(value, 3) if isinstance(value, float) else value, "ghi_chu": note})

    status = {k["ma_cau"]: k["status"] for k in key}
    acc = [c for c in verdicts if status[c] == "accepted"]
    rej = [c for c in verdicts if status[c] == "rejected"]
    acc_pass, rej_pass = sum(verdicts[c] for c in acc), sum(verdicts[c] for c in rej)

    low, high = wilson(acc_pass, len(acc))
    add("ti_le_cau_accepted_dat", acc_pass / len(acc) if acc else 0.0, f"{acc_pass}/{len(acc)}, KTC 95%: {low:.2f}–{high:.2f}")
    population_acc = sum(q["status"] == "accepted" for q in questions)
    population_rej = sum(q["status"] == "rejected" for q in questions)
    metrics = filter_metrics(acc_pass, len(acc), rej_pass, len(rej), population_acc, population_rej)
    add("precision_bo_loc", metrics["precision"], "trong câu giữ lại, bao nhiêu câu tốt")
    add("recall_bo_loc", metrics["recall"], f"đã quy về quy mô thật: {population_acc} accepted, {population_rej} rejected")
    add("ti_le_loai_oan", metrics["wrongly_rejected"], f"{rej_pass}/{len(rej)} câu rejected được người chấm cho đạt")

    bloom = {k["ma_cau"]: k["bloom_level"] for k in key}
    for level in sorted(set(bloom.values())):
        codes = [c for c in acc if bloom[c] == level]
        if not codes:
            continue
        add(f"dat_{level}", sum(verdicts[c] for c in codes) / len(codes), f"{len(codes)} câu accepted")
        for criterion in SCALE_CRITERIA:
            mean = sum(a[c][criterion] + b[c][criterion] for c in codes) / (2 * len(codes))
            add(f"{criterion}_{level}", mean, "điểm trung bình thang 1–5")
    return rows


def main() -> None:
    for path in (SHEET_RATER1, SHEET_RATER2, SAMPLE_KEY):
        if not path.exists():
            fail(f"thiếu {path.name}. Chạy trước: python -m eval.mcq.step3_sample")
    sheet1, sheet2 = read_csv(SHEET_RATER1), read_csv(SHEET_RATER2)
    a, b = parse_sheet(sheet1, SHEET_RATER1.name), parse_sheet(sheet2, SHEET_RATER2.name)
    if set(a) != set(b):
        fail("hai phiếu không cùng danh sách ma_cau.")

    agreement = agreement_rows(a, b)
    write_csv(RESULTS_DIR / "dong_thuan.csv", agreement)
    print("Độ đồng thuận giữa 2 người chấm:")
    for row in agreement:
        kappa = "không xác định" if row["kappa"] == "" else row["kappa"]
        print(f"  {row['tieu_chi']}: kappa={kappa}, giống nhau {row['ti_le_giong_nhau']:.0%}")

    if not SHEET_FINAL.exists():
        write_csv(SHEET_FINAL, build_final_sheet(a, b, sheet1))
    verdicts = parse_final(read_csv(SHEET_FINAL))
    if verdicts is None:
        print(f"\nHai người thảo luận và điền các ô trống trong {SHEET_FINAL.name}, rồi chạy lại lệnh này.")
        return

    rows = quality_rows(verdicts, read_csv(SAMPLE_KEY), a, b, load_questions())
    write_csv(RESULTS_DIR / "chat_luong.csv", rows)
    print("\nChất lượng câu hỏi:")
    for row in rows:
        print(f"  {row['chi_so']}: {row['gia_tri']}  {row['ghi_chu']}")


if __name__ == "__main__":
    main()
