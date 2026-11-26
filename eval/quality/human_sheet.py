"""Lớp B của đặc tả: tạo phiếu chấm người, ẩn phiên bản.

Lấy n cặp câu: mỗi cặp là câu V1 và câu V2 sinh từ CÙNG một chunk slide (so cùng nội dung, giảm nhiễu), chọn
chunk theo tỉ lệ từng bài (phân tầng theo chương). Trộn thứ tự, gán mã H001…, bỏ mọi dấu vết phiên bản (không
có evidence, giải thích hay item_id). Khoá (mã → phiên bản) ghi riêng, người chấm không mở.

Phiếu có thêm 2 cột đúng/sai (J1, J2) để đối chiếu với LLM judge khi chạy lớp J sau này.

Chạy được ngoài container:
  python -m eval.quality.human_sheet --pairs 25
Ra: eval/quality/human/phieu_cham.csv, khoa.csv (không mở), huong_dan_cham.md đã có sẵn trong thư mục.
"""
import argparse
import csv
import random
from pathlib import Path

from eval.quality.common import LETTERS, ROOT, load_cfg, read_jsonl

HUMAN = ROOT / "human"
SCORE_COLS = ["R1_chinh_xac", "R2_dung_duy_nhat", "R3_trong_tam", "R4_muc_nhan_thuc", "R5_nhieu_hop_ly",
              "R6_khong_lo_dap_an", "R7_quyet_dinh", "J1_dap_an_co_can_cu", "J2_mot_dap_an_dung",
              "phuong_an_cung_dung", "ghi_chu"]


def stratified_chunks(common: list, doc_of: dict, n: int, rng: random.Random) -> list:
    by_doc: dict = {}
    for c in common:
        by_doc.setdefault(doc_of.get(c), []).append(c)
    total = len(common)
    quota = {d: max(1, round(n * len(cs) / total)) for d, cs in by_doc.items()}
    while sum(quota.values()) > n:                 # làm tròn lố thì bớt ở bài nhiều nhất
        quota[max(quota, key=quota.get)] -= 1
    picked = []
    for d, cs in by_doc.items():
        picked += rng.sample(sorted(cs), min(quota[d], len(cs)))
    return picked


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", type=int, default=25, help="số chunk; mỗi chunk cho 1 câu V1 + 1 câu V2")
    ap.add_argument("--versions", nargs=2, default=["V1", "V2"])
    ap.add_argument("--data", default=str(ROOT / "data"))
    a = ap.parse_args()
    cfg = load_cfg()
    rng = random.Random(cfg["seed"])
    data = Path(a.data)
    items = {v: {it["chunk_id"]: it for it in read_jsonl(data / f"{v}_items.jsonl")} for v in a.versions}
    common = sorted(set.intersection(*(set(d) for d in items.values())))
    if len(common) < a.pairs:
        print(f"Chỉ có {len(common)} chunk chung, lấy hết.")
    doc_of = {c: items[a.versions[0]][c].get("doc_id") for c in common}
    chunks = stratified_chunks(common, doc_of, min(a.pairs, len(common)), rng)
    chosen = [items[v][c] for c in chunks for v in a.versions]
    rng.shuffle(chosen)

    HUMAN.mkdir(exist_ok=True)
    sheet, key = [], []
    for i, it in enumerate(chosen, 1):
        code = f"H{i:03d}"
        sheet.append({"ma_cau": code, "cau_hoi": it["stem"], **{k: it["options"][k] for k in LETTERS},
                      "dap_an": it["key"], "noi_dung_slide": it["source_context"], **{c: "" for c in SCORE_COLS}})
        key.append({"ma_cau": code, "item_id": it["item_id"], "version": it["version"], "chunk_id": it["chunk_id"],
                    "doc_id": it.get("doc_id")})
    for name, rows in (("phieu_cham.csv", sheet), ("khoa.csv", key)):
        path = HUMAN / name
        if name == "phieu_cham.csv" and path.exists():
            raise SystemExit(f"{path} đã có (có thể đã chấm). Đổi tên hoặc xoá trước khi tạo lại.")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    by_doc: dict = {}
    for c in chunks:
        by_doc[doc_of.get(c)] = by_doc.get(doc_of.get(c), 0) + 1
    print(f"{len(sheet)} câu ({len(chunks)} chunk × {len(a.versions)} phiên bản), theo bài: {by_doc}")
    print(f"Phiếu: {HUMAN / 'phieu_cham.csv'}  ·  Khoá (không mở): {HUMAN / 'khoa.csv'}")


if __name__ == "__main__":
    main()
