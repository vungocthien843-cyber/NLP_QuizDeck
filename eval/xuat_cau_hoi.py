"""Xuất toàn bộ câu hỏi của một bộ đánh giá ra MỘT file Excel để người xem tự kiểm tra:
câu hỏi, 4 phương án (đã xáo đúng như khi chấm), đáp án đúng, giải thích, câu trích làm căn cứ, nội dung slide,
và với V3: loại hiểu nhầm + nguồn sinh (ViT5 / LLM) của từng phương án sai. Kèm danh sách slide KHÔNG sinh được câu.

  python -m eval.xuat_cau_hoi --data eval/quality/data_nlp --results eval/v2/results/NLP
Kết quả mặc định: <results>/cau_hoi_<tên bộ>.xlsx
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Arial"
LETTERS = "ABCD"
HEAD = PatternFill("solid", fgColor="1F4E78")
KEY_FILL = PatternFill("solid", fgColor="E2EFDA")       # xanh nhạt: phương án đúng
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")      # vàng: cột để người kiểm tra ghi chú
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TYPE_VI = {"nham_khai_niem_lan_can": "Nhầm khái niệm lân cận", "khai_quat_qua_muc": "Khái quát quá mức",
           "dao_nhan_qua": "Đảo nhân quả", "sai_thu_tu_buoc": "Sai thứ tự bước",
           "gan_nham_thuoc_tinh": "Gán nhầm thuộc tính", "dung_nhung_khong_tra_loi": "Đúng nhưng không trả lời",
           "sai_mot_chi_tiet": "Sai một chi tiết", "khong_ro": "Không rõ"}
VERSION_VI = {"V1": "V1 – baseline (1 lần gọi LLM)", "V3": "V3 – đề xuất (câu nhiễu chẩn đoán)"}


REASON_VI = {"form": "Lỗi hình thức ở hậu kiểm (độ dài, từ cấm, chép đáp án…)", "validator": "Không qua hậu kiểm",
             "selection": "Không chọn được bộ 3 phương án sai thoả điều kiện δ", "key": "Không tạo được đáp án đúng",
             "stem": "Không tạo được câu hỏi", "distractors": "Không đủ phương án sai sau lọc"}


def reason_vi(r) -> str:
    if not isinstance(r, str):
        r = json.dumps(r, ensure_ascii=False)
    first = r.splitlines()[0] if r else ""
    for k, vi in REASON_VI.items():
        if first == k or first.startswith(k + ":"):
            return vi
    return (first[:300] + "…") if len(first) > 300 else first


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def clean_slide(text: str) -> str:
    text = re.sub(r'<chunk[^>]*nguồn="([^"]*)"[^>]*>', r"── \1 ──", text or "")
    text = re.sub(r"</?chunk[^>]*>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def doc_names(ids: set) -> dict:
    try:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import Document
        with SessionLocal() as db:
            return {d.id: d.filename for d in db.scalars(select(Document).where(Document.id.in_(ids)))}
    except Exception:                         # chạy ngoài container: không có DB
        return {}


def _sheet(wb, title: str, cols: list[tuple[str, int]], rows: list[list], key_cols: dict[int, int] | None = None,
           note_col: int | None = None) -> None:
    ws = wb.create_sheet(title)
    for j, (h, w) in enumerate(cols, 1):
        c = ws.cell(1, j, h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = NOTE_FILL if j == note_col else HEAD
        if j == note_col:
            c.font = Font(name=FONT, bold=True, size=10)
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[1].height = 36
    for i, row in enumerate(rows, 2):
        for j, v in enumerate(row, 1):
            if isinstance(v, str):                     # ký tự điều khiển (ví dụ \b, \x0b từ slide/regex) Excel không nhận
                v = ILLEGAL_CHARACTERS_RE.sub("", v)
            c = ws.cell(i, j, v)
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = BORDER
            if j == note_col:
                c.fill = NOTE_FILL
        if key_cols and i - 2 in key_cols:                       # tô xanh ô phương án đúng
            ws.cell(i, key_cols[i - 2]).fill = KEY_FILL
            ws.cell(i, key_cols[i - 2]).font = Font(name=FONT, size=10, bold=True)
        longest = max((len(str(v or "")) / max(cols[j][1], 1) for j, v in enumerate(row)), default=1)
        ws.row_dimensions[i].height = min(409, 14 * (int(longest) + 2))
    if note_col and rows:
        dv = DataValidation(type="list", formula1='"OK,Lỗi nhẹ,Lỗi nặng"', allow_blank=True)
        L = get_column_letter(note_col)
        dv.add(f"{L}2:{L}{len(rows) + 1}")
        ws.add_data_validation(dv)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="eval/quality/data_nlp")
    ap.add_argument("--results", default="eval/v2/results/NLP")
    ap.add_argument("--out")
    a = ap.parse_args()
    data, res = Path(a.data), Path(a.results)
    cfg_of = {"V1": "C0", "V3": "C5"}
    items = {v: read_jsonl(data / f"{v}_items.jsonl") for v in cfg_of}
    recs = {v: read_jsonl(res / f"questions_{c}.jsonl") for v, c in cfg_of.items()}
    if not any(items.values()):
        raise SystemExit(f"Không có V1_items.jsonl / V3_items.jsonl trong {data}. Chạy export trước.")
    by_seed = {v: {r["meta"]["seed_chunk"]: r for r in rs} for v, rs in recs.items()}
    names = doc_names({it.get("doc_id") for xs in items.values() for it in xs if it.get("doc_id")})

    def bai(it):
        d = it.get("doc_id")
        return names.get(d) or (f"bài {d}" if d is not None else "")

    wb = Workbook()
    ws = wb.active
    ws.title = "Hướng dẫn"
    n = {v: len(xs) for v, xs in items.items()}
    seeds = max((len(rs) for rs in recs.values()), default=0)
    lines = [("CÂU HỎI CỦA BỘ ĐÁNH GIÁ", f"{data.name} (kết quả sinh: {res})"),
             ("Số slide hạt giống", seeds),
             *[(f"Số câu {VERSION_VI[v]}", n[v]) for v in cfg_of],
             ("Cách đọc", "Mỗi trang V1 / V3: một dòng một câu. Ô xanh = phương án ĐÚNG. 4 phương án đã xáo đúng như "
                          "khi chấm tự động. Cột 'Câu trích làm căn cứ' là câu trong slide mà hệ thống dùng để chứng "
                          "minh đáp án. Trang V3 có thêm loại hiểu nhầm và nguồn sinh (ViT5 / LLM) của từng phương án sai."),
             ("Ghi chú kiểm tra", "Cột vàng 'Kiểm tra': chọn OK / Lỗi nhẹ / Lỗi nặng và ghi lý do (không bắt buộc). "
                                  "Dùng bộ lọc ở dòng tiêu đề để xem theo chương."),
             ("Trang 'Theo slide'", "Đặt câu V1 và V3 sinh từ CÙNG một slide cạnh nhau để so sánh trực tiếp."),
             ("Trang 'Không sinh được'", "Các slide mà phiên bản đó không tạo được câu đạt hậu kiểm, kèm lý do.")]
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 110
    for i, (k, v) in enumerate(lines, 1):
        ws.cell(i, 1, k).font = Font(name=FONT, bold=True, size=12 if i == 1 else 10)
        c = ws.cell(i, 2, v)
        c.font = Font(name=FONT, size=10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    r0 = len(lines) + 2
    ws.cell(r0, 1, "Số câu theo bài").font = Font(name=FONT, bold=True)
    for j, h in enumerate(["Bài", *cfg_of], 1):
        ws.cell(r0 + 1, j, h).font = Font(name=FONT, bold=True)
    cnt = {v: Counter(bai(it) for it in xs) for v, xs in items.items()}
    for i, b in enumerate(sorted(set().union(*cnt.values())), r0 + 2):
        ws.cell(i, 1, b).font = Font(name=FONT, size=10)
        for j, v in enumerate(cfg_of, 2):
            ws.cell(i, j, cnt[v].get(b, 0)).font = Font(name=FONT, size=10)

    for v in cfg_of:
        cols = [("STT", 5), ("Bài", 22), ("Slide", 6), ("Mức Bloom", 10), ("Câu hỏi", 40), ("A", 26), ("B", 26),
                ("C", 26), ("D", 26), ("Đáp án đúng", 7), ("Giải thích", 36), ("Câu trích làm căn cứ", 34)]
        if v == "V3":
            cols += [("Loại hiểu nhầm của 3 phương án sai", 30), ("Nguồn sinh", 16)]
        cols += [("Nội dung slide", 70), ("Kiểm tra", 12), ("Ghi chú", 24)]
        rows, keys = [], {}
        items_v = sorted(items[v], key=lambda it: (bai(it), it.get("slide") or 0, it["chunk_id"]))
        for i, it in enumerate(items_v):
            q = (by_seed[v].get(it["chunk_id"]) or {}).get("question") or {}
            row = [i + 1, bai(it), it.get("slide"), it.get("bloom_target"), it["stem"],
                   *[it["options"][x] for x in LETTERS], it["key"], q.get("explanation") or "", it.get("evidence") or ""]
            if v == "V3":
                et, src = it.get("error_types") or {}, it.get("sources") or {}
                row += ["\n".join(f"{x}: {TYPE_VI.get(et.get(x), et.get(x) or '—')}" for x in LETTERS if x in et),
                        "\n".join(f"{x}: {src.get(x) or '—'}" for x in LETTERS if x in src)]
            row += [clean_slide(it.get("source_context") or ""), None, None]
            rows.append(row)
            keys[i] = 6 + LETTERS.index(it["key"])                # cột A nằm ở vị trí 6
        _sheet(wb, f"{v} ({len(rows)} câu)", cols, rows, keys, note_col=len(cols) - 1)

    # So sánh theo slide
    v1 = {it["chunk_id"]: it for it in items["V1"]}
    v3 = {it["chunk_id"]: it for it in items["V3"]}
    both = sorted(set(v1) | set(v3), key=lambda c: (bai(v1.get(c) or v3.get(c)), (v1.get(c) or v3.get(c)).get("slide") or 0))

    def brief(it):
        if not it:
            return "(không sinh được)"
        return it["stem"] + "\n" + "\n".join(f"{'✔' if x == it['key'] else '  '} {x}. {it['options'][x]}" for x in LETTERS)
    cols = [("Bài", 22), ("Slide", 6), ("Câu V1 (✔ = đáp án đúng)", 55), ("Câu V3 (✔ = đáp án đúng)", 55),
            ("Nội dung slide", 70)]
    rows = [[bai(v1.get(c) or v3.get(c)), (v1.get(c) or v3.get(c)).get("slide"), brief(v1.get(c)), brief(v3.get(c)),
             clean_slide((v1.get(c) or v3.get(c)).get("source_context") or "")] for c in both]
    _sheet(wb, "Theo slide", cols, rows)

    # Không sinh được
    fail = []
    for v, rs in recs.items():
        for r in rs:
            if not (r.get("question") and r["meta"].get("passed")):
                m = r["meta"]
                fail.append([v, m.get("seed_chunk"), m.get("bloom"), m.get("reason") or m.get("failed")
                             or (m.get("details") or {}).get("reason") or "không qua hậu kiểm"])
    _sheet(wb, "Không sinh được", [("Phiên bản", 10), ("Mã slide (chunk)", 14), ("Mức Bloom", 10), ("Lý do", 80)],
           [[a_, b_, c_, reason_vi(d_)] for a_, b_, c_, d_ in fail])

    out = Path(a.out) if a.out else res / f"cau_hoi_{data.name.replace('data_', '')}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Đã xuất {sum(n.values())} câu ({', '.join(f'{v}: {k}' for v, k in n.items())}) → {out}")


if __name__ == "__main__":
    main()
