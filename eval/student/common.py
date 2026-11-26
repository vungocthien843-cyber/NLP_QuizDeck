"""Dùng chung cho thử nghiệm sinh viên (Mốc 3, G4/G5)."""
import csv
import os
from pathlib import Path

ROOT = Path(os.environ.get("STUDENT_EXP_DIR") or Path(__file__).parent)   # đổi được khi chạy test
DATA = ROOT / "data"
RESULTS = ROOT / "results"
ITEMS = DATA / "de_thu_nghiem.csv"          # câu nào ở đề nào, phiên bản nào (người tổ chức xem, KHÔNG đưa sinh viên)
ROSTER = DATA / "danh_sach_ma.csv"          # mã → nhóm (người tổ chức giữ)
CODES = DATA / "phat_ma_sinh_vien.csv"      # mã để phát cho sinh viên (không có nhóm)


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
