"""Dùng chung cho đánh giá người của v3 (kế hoạch v3: G2 chấm câu hỏi V1 vs V3, G3 gán nhãn hiểu nhầm)."""
import csv
import json
import os
import re
import unicodedata
from pathlib import Path

# HUMAN_V3_DIR: đổi chỗ lưu phiếu (dùng cho test); mặc định là thư mục này
ROOT = Path(os.environ.get("HUMAN_V3_DIR") or Path(__file__).parent)
DATA = ROOT / "data"
RESULTS = ROOT / "results"

RATERS = ("nguoi1", "nguoi2")
# G2 — mức câu hỏi
Q_BINARY = ("dung_kien_thuc", "mot_dap_an_dung", "tu_dung_duoc")
Q_SCALE = ("ro_rang", "phuong_an_sai_hop_ly")
# G2 — mức từng phương án sai
D_BINARY = ("chac_chan_sai", "the_hien_hieu_nham")
D_SCALE = ("hop_ly",)
UNCLEAR = "khong_ro"
KINDS = ("thu", "cau_hoi", "dap_an_nhieu", "nhan")       # thu = chấm thử chung, không tính kết quả

KEY_Q = DATA / "khoa_cau_hoi.csv"          # người chấm KHÔNG mở: mã câu → phiên bản
KEY_LABEL = DATA / "khoa_nhan.csv"         # người chấm KHÔNG mở: mã → nhãn LLM
RATERS_FILE = DATA / "nguoi_cham.json"     # nguoi1/nguoi2 → họ tên, tên file phiếu


def slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name.replace("Đ", "D").replace("đ", "d"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def raters() -> dict[str, dict]:
    """nguoi1/nguoi2 → {"ten": ..., "file": ...}; chưa đặt tên thì dùng mặc định."""
    if RATERS_FILE.exists():
        return json.loads(RATERS_FILE.read_text(encoding="utf-8"))
    return {r: {"ten": r, "file": f"Phieu_cham_{r}.xlsx"} for r in RATERS}


def workbook(rater: str) -> Path:
    return DATA / raters()[rater]["file"]


def rater_name(rater: str) -> str:
    return raters()[rater]["ten"]


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: Excel mở đúng tiếng Việt
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
