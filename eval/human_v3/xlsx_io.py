"""Phiếu chấm dạng Excel: một file cho mỗi người chấm, có hướng dẫn, ô chọn sẵn (data validation), tô vàng ô cần điền,
bảng tiến độ. Tiêu đề cột hiển thị tiếng Việt; dòng 1 ẩn giữ khoá máy đọc để phân tích không phụ thuộc cách hiển thị."""
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Arial"
SHEET = {"thu": "1. Chấm thử", "cau_hoi": "2. Câu hỏi", "dap_an_nhieu": "3. Phương án sai", "nhan": "4. Gán nhãn"}
TYPES_SHEET = "Bảng loại hiểu nhầm"
GUIDE_SHEET = "0. Hướng dẫn"

# (khoá, tiêu đề hiển thị, độ rộng, loại ô: None = chỉ đọc | "01" | "15" | "nhan" | "text")
Q_COLS = [("ma_cau", "Mã câu", 8, None), ("cau_hoi", "Câu hỏi", 42, None), ("A", "A", 26, None),
          ("B", "B", 26, None), ("C", "C", 26, None), ("D", "D", 26, None), ("dap_an", "Đáp án\nđúng", 8, None),
          ("dung_kien_thuc", "Đúng\nkiến thức\n(0/1)", 11, "01"), ("mot_dap_an_dung", "Một đáp\nán đúng\n(0/1)", 11, "01"),
          ("tu_dung_duoc", "Tự đứng\nđược\n(0/1)", 11, "01"), ("ro_rang", "Rõ ràng\n(1–5)", 10, "15"),
          ("phuong_an_sai_hop_ly", "Phương án\nsai hợp lý\n(1–5)", 12, "15"), ("ghi_chu", "Ghi chú", 24, "text"),
          ("evidence", "Câu trích làm căn cứ", 34, None), ("noi_dung_slide", "Nội dung slide", 70, None)]
D_COLS = [("ma_pa", "Mã PA", 8, None), ("ma_cau", "Mã câu", 8, None), ("cau_hoi", "Câu hỏi", 44, None),
          ("dap_an_dung", "Đáp án đúng", 32, None), ("phuong_an_sai", "Phương án SAI cần chấm", 36, None),
          ("chac_chan_sai", "Chắc chắn\nsai (0/1)", 11, "01"), ("hop_ly", "Hợp lý\n(1–5)", 10, "15"),
          ("the_hien_hieu_nham", "Thể hiện\nhiểu nhầm\n(0/1)", 12, "01"), ("ghi_chu", "Ghi chú", 24, "text")]
L_COLS = [("ma_nhan", "Mã", 7, None), ("cau_hoi", "Câu hỏi", 40, None), ("dap_an_dung", "Đáp án đúng", 30, None),
          ("phuong_an_sai", "Phương án SAI cần gán nhãn", 36, None), ("nhan", "Loại hiểu nhầm\n(chọn trong danh sách)", 30, "nhan"),
          ("ghi_chu", "Ghi chú (loại thứ 2 nếu phân vân)", 26, "text"), ("noi_dung_slide", "Nội dung slide", 70, None)]
COLS = {"thu": Q_COLS, "cau_hoi": Q_COLS, "dap_an_nhieu": D_COLS, "nhan": L_COLS}

INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")     # vàng nhạt: ô cần điền
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _row_height(row: dict, cols) -> float:
    lines = 1
    for key, _, width, _ in cols:
        text = str(row.get(key) or "")
        est = sum(max(1, -(-len(part) // max(int(width * 1.1), 1))) for part in text.split("\n"))
        lines = max(lines, est)
    return min(409, 15 * lines + 4)


def _data_sheet(wb, kind: str, rows: list[dict], codes: list[str]) -> None:
    ws = wb.create_sheet(SHEET[kind])
    cols = COLS[kind]
    for j, (key, title, width, typ) in enumerate(cols, 1):
        ws.cell(1, j, key)                                   # dòng 1 (ẩn): khoá cho máy đọc
        c = ws.cell(2, j, title)
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEAD_FILL if typ is None else PatternFill("solid", fgColor="BF8F00")
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.row_dimensions[1].hidden = True
    ws.row_dimensions[2].height = 48
    for i, r in enumerate(rows, 3):
        for j, (key, _, _, typ) in enumerate(cols, 1):
            c = ws.cell(i, j, r.get(key) if typ is None else (r.get(key) or None))
            c.font = Font(name=FONT, size=10, bold=key in ("ma_cau", "ma_pa", "ma_nhan", "dap_an"))
            c.alignment = Alignment(wrap_text=True, vertical="top",
                                    horizontal="center" if typ in ("01", "15") or key in ("dap_an",) else "left")
            c.border = BORDER
            if typ is not None:
                c.fill = INPUT_FILL
        ws.row_dimensions[i].height = _row_height(r, cols)
    last = len(rows) + 2
    for typ, formula, msg in (("01", '"0,1"', "Chỉ điền 0 hoặc 1"), ("15", '"1,2,3,4,5"', "Chỉ điền 1 đến 5"),
                              ("nhan", f"'{TYPES_SHEET}'!$A$2:$A${len(codes) + 1}", "Chọn mã trong danh sách")):
        cols_t = [get_column_letter(j) for j, (_, _, _, t) in enumerate(cols, 1) if t == typ]
        if not cols_t or not rows:
            continue
        dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=True,
                            errorTitle="Giá trị không hợp lệ", error=msg)
        for L in cols_t:
            dv.add(f"{L}3:{L}{last}")
        ws.add_data_validation(dv)
    ws.freeze_panes = "B3"
    ws.sheet_view.zoomScale = 90


def _types_sheet(wb, types: dict[str, dict]) -> list[str]:
    ws = wb.create_sheet(TYPES_SHEET)
    heads = ["Mã (chọn ở cột Loại hiểu nhầm)", "Tên", "Dấu hiệu nhận biết", "Ví dụ"]
    widths = [30, 26, 60, 60]
    for j, (h, w) in enumerate(zip(heads, widths, strict=True), 1):
        c = ws.cell(1, j, h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = w
    codes = list(types)
    for i, code in enumerate(codes, 2):
        t = types[code]
        cue = t.get("dau_hieu") or t.get("mo_ta") or ""
        cue = "; ".join(cue) if isinstance(cue, list) else cue
        ex = t.get("vi_du") or ""
        ex = "; ".join(map(str, ex)) if isinstance(ex, list) else str(ex)
        for j, v in enumerate([code, t.get("ten", ""), cue, ex], 1):
            c = ws.cell(i, j, v)
            c.font = Font(name=FONT, size=10, bold=j == 1)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = BORDER
        ws.row_dimensions[i].height = 60
    ws.freeze_panes = "A2"
    return codes


def _guide_sheet(wb, name: str, counts: dict[str, int], guide_lines: list[tuple[str, str]]) -> None:
    ws = wb.active
    ws.title = GUIDE_SHEET
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 110
    ws["A1"] = f"PHIẾU CHẤM CÂU HỎI TRẮC NGHIỆM — {name}"
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color="1F4E78")
    r = 3
    ws.cell(r, 1, "Tiến độ").font = Font(name=FONT, bold=True, size=12)
    r += 1
    for kind in ("thu", "cau_hoi", "dap_an_nhieu", "nhan"):
        if not counts.get(kind):
            continue
        cols = COLS[kind]
        inputs = [get_column_letter(j) for j, (_, _, _, t) in enumerate(cols, 1) if t in ("01", "15", "nhan")]
        last = counts[kind] + 2
        sh = f"'{SHEET[kind]}'"
        filled = "+".join(f"COUNTA({sh}!{L}3:{L}{last})" for L in inputs)
        total = counts[kind] * len(inputs)
        ws.cell(r, 1, SHEET[kind]).font = Font(name=FONT, size=10)
        c = ws.cell(r, 2, f"=({filled})/{total}")
        c.number_format = "0%"
        c.font = Font(name=FONT, size=10, bold=True)
        c.alignment = Alignment(horizontal="left")
        ws.cell(r, 3, f"{counts[kind]} dòng").font = Font(name=FONT, size=9, color="808080")
        r += 1
    r += 1
    legend = ws.cell(r, 1, "Ô cần điền")
    legend.font = Font(name=FONT, bold=True, size=10)
    s = ws.cell(r, 2, "Ô nền vàng, cột tiêu đề nâu (bấm vào ô → mũi tên ▼ để chọn). Các ô khác chỉ để đọc, không sửa.")
    s.fill = INPUT_FILL
    s.font = Font(name=FONT, size=10)
    r += 2
    for title, body in guide_lines:
        if title:
            ws.cell(r, 1, title).font = Font(name=FONT, bold=True, size=11, color="1F4E78")
        c = ws.cell(r, 2, body)
        c.font = Font(name=FONT, size=10, bold=title == "" and body.startswith("▶"))
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = max(15, 15 * (len(body) // 120 + body.count("\n") + 1))
        r += 1


def write_workbook(path: Path, name: str, rows: dict[str, list[dict]], types: dict[str, dict],
                   guide_lines: list[tuple[str, str]]) -> None:
    wb = Workbook()
    _guide_sheet(wb, name, {k: len(v) for k, v in rows.items()}, guide_lines)
    codes = list(types)
    for kind in ("thu", "cau_hoi", "dap_an_nhieu", "nhan"):
        if kind in rows:
            _data_sheet(wb, kind, rows[kind], codes)
    _types_sheet(wb, types)
    wb.properties.creator = "RAG Quiz — đánh giá người v3"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def read_kind(path: Path, kind: str) -> list[dict]:
    """Đọc một phiếu: khoá ở dòng 1 (ẩn), dữ liệu từ dòng 3. Số trả về dạng chuỗi như CSV ('1', '4')."""
    wb = load_workbook(path, data_only=True, read_only=True)
    if SHEET[kind] not in wb.sheetnames:
        return []
    rows = list(wb[SHEET[kind]].iter_rows(values_only=True))
    if len(rows) < 3:
        return []
    keys = [str(k) if k is not None else "" for k in rows[0]]
    out = []
    for vals in rows[2:]:
        if all(v is None for v in vals):
            continue
        rec = {}
        for k, v in zip(keys, vals, strict=False):
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            rec[k] = "" if v is None else str(v)
        out.append(rec)
    return out


def fill_kind(path: Path, kind: str, rows: list[dict]) -> None:
    """Ghi điểm vào các ô cần điền (dùng cho test / nhập lại từ CSV)."""
    wb = load_workbook(path)
    ws = wb[SHEET[kind]]
    keys = [c.value for c in ws[1]]
    idc = keys[0]
    pos = {ws.cell(i, 1).value: i for i in range(3, ws.max_row + 1)}
    inputs = {k for k, _, _, t in COLS[kind] if t is not None}
    for r in rows:
        i = pos[r[idc]]
        for j, k in enumerate(keys, 1):
            if k in inputs and k in r:
                v = r[k]
                ws.cell(i, j, int(v) if str(v).isdigit() else (v or None))
    wb.save(path)


def filled_any(path: Path, kind: str) -> bool:
    if not path.exists():
        return False
    inputs = {k for k, _, _, t in COLS[kind] if t in ("01", "15", "nhan")}
    return any(r.get(k) for r in read_kind(path, kind) for k in inputs)
