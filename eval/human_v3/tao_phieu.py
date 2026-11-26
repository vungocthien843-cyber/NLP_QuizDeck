"""Tạo phiếu chấm cho 2 người (kế hoạch v3, G2 + G3). Chạy SAU G1 và scripts\\_da_chay\\2_chon_lai_v3.bat.

G2  So sánh V1 (C0) và V3 (C5) trên CÙNG hạt giống. Người chấm không biết câu thuộc phiên bản nào: hai phiên bản
    được trộn chung, mã câu ngẫu nhiên. Hai phiếu cho mỗi người:
      phieu_cau_hoi_<người>.csv       mỗi câu một dòng: đúng kiến thức, một đáp án đúng, tự đứng được, rõ ràng,
                                      phương án sai hợp lý
      phieu_dap_an_nhieu_<người>.csv  mỗi PHƯƠNG ÁN SAI một dòng: chắc chắn sai, hợp lý (1–5), thể hiện hiểu nhầm
G3  60 phương án sai của V3, chia đều theo nhãn hiểu nhầm LLM đã gắn. Người chấm tự gán nhãn, không thấy nhãn LLM:
      phieu_nhan_<người>.csv
Khoá (người chấm KHÔNG mở): khoa_cau_hoi.csv, khoa_nhan.csv. Chấm thử chung trước: phieu_cham_thu.csv.

Chạy trong container API:
  python -m eval.human_v3.tao_phieu                                  # mặc định 40 cặp, 60 nhãn, 4 câu chấm thử
  python -m eval.human_v3.tao_phieu --pairs 30 --labels 50 --force   # --force: ghi đè, MẤT điểm đã chấm
"""
import argparse
import json
import random
import re
import shutil
from collections import defaultdict
from pathlib import Path

from eval.human_v3.common import (D_BINARY, D_SCALE, DATA, KEY_LABEL, KEY_Q, Q_BINARY, Q_SCALE, RATERS,
                                  RATERS_FILE, UNCLEAR, slug, write_csv)
from eval.human_v3.guide import GUIDE

LETTERS = "ABCD"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def pair_items(data: Path) -> list[tuple[dict, dict]]:
    """Cặp (V1, V3) cùng chunk hạt giống: so sánh có kiểm soát nội dung slide."""
    v1 = {it["chunk_id"]: it for it in read_jsonl(data / "V1_items.jsonl")}
    v3 = {it["chunk_id"]: it for it in read_jsonl(data / "V3_items.jsonl")}
    return [(v1[c], v3[c]) for c in sorted(set(v1) & set(v3))]


def stratified(pairs: list, n: int, rng: random.Random) -> list:
    """Rải đều theo bài học (doc_id) để không dồn vào một bài."""
    by_doc = defaultdict(list)
    for p in pairs:
        by_doc[p[0].get("doc_id")].append(p)
    for g in by_doc.values():
        rng.shuffle(g)
    out = []
    while len(out) < n and any(by_doc.values()):
        for d in sorted(by_doc, key=str):
            if by_doc[d] and len(out) < n:
                out.append(by_doc[d].pop())
    return out


def clean_slide(text: str) -> str:
    """<chunk id=.. nguồn="Slide 8"> … </chunk> → '── Slide 8 ──' cho dễ đọc trong Excel."""
    text = re.sub(r'<chunk[^>]*nguồn="([^"]*)"[^>]*>', r"── \1 ──", text or "")
    text = re.sub(r"</?chunk[^>]*>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def q_row(code: str, it: dict) -> dict:
    return {"ma_cau": code, "cau_hoi": it["stem"], **{x: it["options"][x] for x in LETTERS},
            "dap_an": it["key"], "evidence": it.get("evidence") or "",
            "noi_dung_slide": clean_slide(it.get("source_context") or ""),
            **{c: "" for c in (*Q_BINARY, *Q_SCALE)}, "ghi_chu": ""}


def d_rows(code: str, it: dict, counter: list[int]) -> list[dict]:
    rows = []
    for x in LETTERS:
        if x == it["key"]:
            continue
        counter[0] += 1
        rows.append({"ma_pa": f"P{counter[0]:04d}", "ma_cau": code, "chu": x, "cau_hoi": it["stem"],
                     "dap_an_dung": it["options"][it["key"]], "phuong_an_sai": it["options"][x],
                     **{c: "" for c in (*D_BINARY, *D_SCALE)}, "ghi_chu": ""})
    return rows


def label_pool(results: Path) -> list[dict]:
    """Phương án sai được chọn của V3 kèm nhãn LLM (lấy từ report của pipeline: v2.picked)."""
    pool = []
    for r in read_jsonl(results / "questions_C5.jsonl"):
        q, m = r.get("question"), r["meta"]
        if not q or not m.get("passed"):
            continue
        for p in (m.get("v2") or {}).get("picked") or []:
            pool.append({"chunk_id": m["seed_chunk"], "stem": q["stem"], "answer": q["answer"], "text": p["text"],
                         "llm_label": p.get("error_type") or UNCLEAR, "context": q.get("context") or ""})
    return pool


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="eval/quality/data_g1", help="thư mục V1_items.jsonl / V3_items.jsonl")
    ap.add_argument("--results", default="eval/v2/results/G1", help="thư mục questions_C5.jsonl")
    ap.add_argument("--pairs", type=int, default=40, help="số cặp V1–V3 (mỗi cặp 2 câu)")
    ap.add_argument("--labels", type=int, default=60, help="số phương án sai cần gán nhãn hiểu nhầm")
    ap.add_argument("--pilot", type=int, default=4, help="số câu chấm thử chung (không tính kết quả)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ten", nargs=2, metavar=("NGUOI1", "NGUOI2"), default=["Người chấm 1", "Người chấm 2"],
                    help='họ tên 2 người chấm, ví dụ --ten "Bùi Minh Ảnh" "Lê Đình Trung"')
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not a.force and (KEY_Q.exists() or RATERS_FILE.exists()):
        raise SystemExit("Phiếu chấm đã có. Tạo lại sẽ MẤT điểm đã chấm; thêm --force nếu chắc chắn.")
    rng = random.Random(a.seed)

    # ---------- G2 ----------
    pairs = pair_items(Path(a.data))
    if not pairs:
        raise SystemExit(f"Không có cặp V1–V3 chung hạt giống trong {a.data}. Đã chạy G1 và scripts\\_da_chay\\2_chon_lai_v3.bat chưa?")
    pilot = stratified(pairs, a.pilot, rng)
    rest = [p for p in pairs if p not in pilot]
    chosen = stratified(rest, a.pairs, rng)
    items = [(v, it) for pair in chosen for v, it in (("V1", pair[0]), ("V3", pair[1]))]
    rng.shuffle(items)
    codes = [f"H{i:03d}" for i in rng.sample(range(1, len(items) + 1), len(items))]   # mã không theo thứ tự trộn
    q_rows, d_all, key, counter = [], [], [], [0]
    for code, (version, it) in sorted(zip(codes, items), key=lambda t: t[0]):
        q_rows.append(q_row(code, it))
        d_all += d_rows(code, it, counter)
        key.append({"ma_cau": code, "phien_ban": version, "item_id": it["item_id"], "chunk_id": it["chunk_id"],
                    "doc_id": it.get("doc_id")})
    write_csv(KEY_Q, key)
    pilot_rows = [q_row(f"T{i:02d}", it) for i, (_, it) in
                  enumerate(((v, p[k]) for p in pilot for k, v in ((0, "V1"), (1, "V3"))), 1)]

    # ---------- G3 ----------
    pool = label_pool(Path(a.results))
    by_label = defaultdict(list)
    for p in pool:
        by_label[p["llm_label"]].append(p)
    for g in by_label.values():
        rng.shuffle(g)
    picked = []
    while len(picked) < a.labels and any(by_label.values()):      # chia đều theo nhãn LLM (nhãn hiếm vẫn có mặt)
        for lb in sorted(by_label):
            if by_label[lb] and len(picked) < a.labels:
                picked.append(by_label[lb].pop())
    rng.shuffle(picked)
    lab_rows = [{"ma_nhan": f"N{i:03d}", "cau_hoi": p["stem"], "dap_an_dung": p["answer"],
                 "phuong_an_sai": p["text"], "noi_dung_slide": clean_slide(p["context"]), "nhan": "", "ghi_chu": ""}
                for i, p in enumerate(picked, 1)]
    write_csv(KEY_LABEL, [{"ma_nhan": row["ma_nhan"], "nhan_llm": p["llm_label"], "chunk_id": p["chunk_id"]}
                          for row, p in zip(lab_rows, picked, strict=True)])

    # ---------- Ghi phiếu Excel cho từng người + thư mục gửi đi ----------
    from app.prompts import misconception_types
    from eval.human_v3.xlsx_io import write_workbook

    types = {**misconception_types(), UNCLEAR: {"ten": "Không rõ", "dau_hieu": "Không loại nào ở trên phù hợp, "
                                                "hoặc phương án sai ngẫu nhiên / lạc đề", "vi_du": "—"}}
    info = {}
    for r, name in zip(RATERS, a.ten, strict=True):
        fname = f"Phieu_cham_{slug(name)}.xlsx"
        info[r] = {"ten": name, "file": fname}
        write_workbook(DATA / fname, name, {"thu": pilot_rows, "cau_hoi": q_rows, "dap_an_nhieu": d_all,
                                            "nhan": lab_rows}, types, GUIDE)
        dst = DATA / f"gui_{slug(name)}"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(DATA / fname, dst / fname)
        shutil.copy(Path(__file__).parent / "huong_dan_cham.md", dst / "Huong_dan_cham.md")
    RATERS_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"G2: {len(chosen)} cặp = {len(q_rows)} câu, {len(d_all)} phương án sai; chấm thử {len(pilot) * 2} câu")
    print(f"G3: {len(lab_rows)} phương án sai cần gán nhãn (nhãn LLM: "
          f"{dict(sorted(((k, sum(p['llm_label'] == k for p in picked)) for k in by_label)))})")
    for r in RATERS:
        print(f"  {info[r]['ten']}: gửi thư mục {DATA / ('gui_' + slug(info[r]['ten']))}")
    print("KHÔNG gửi khoa_*.csv. Khi nhận lại: chép file Phieu_cham_*.xlsx đã điền đè vào "
          f"{DATA} rồi chạy scripts\\6_phan_tich_phieu_nguoi.bat.")


if __name__ == "__main__":
    main()
