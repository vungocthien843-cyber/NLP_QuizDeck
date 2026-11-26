"""Ảnh slide cho giao diện học và tô vàng câu trích dẫn trên slide.

Dùng lại kết quả của bước nạp slide: PNG từng trang trong data/renders/{document_id}/ và file PDF
(PPTX đã được LibreOffice chuyển sang PDF ở cùng thư mục; file tải lên là PDF thì dùng chính nó).
"""
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import pymupdf

from app.config import get_config, get_settings
from app.models import Document

HIGHLIGHT_COLOR = (1.0, 0.86, 0.2)
MIN_BLOCK_WORDS = 3         # chỉ tính các đoạn khớp liên tiếp từ 3 từ trở lên
MIN_COVERAGE = 0.5          # khớp dưới 50% số từ của câu trích → coi như không có trên slide này
EXACT_COVERAGE = 0.9        # khớp từ 90% → coi là đúng slide chứa câu trích


def render_dir(document_id: int) -> Path:
    return get_settings().render_dir / str(document_id)


def png_path(document_id: int, slide_no: int) -> Path:
    return render_dir(document_id) / f"slide_{slide_no:03d}.png"


def slide_count(document_id: int) -> int:
    d = render_dir(document_id)
    return len(list(d.glob("slide_*.png"))) if d.is_dir() else 0


def png_size(document_id: int, slide_no: int) -> tuple[int, int] | None:
    """(rộng, cao) đọc từ header PNG, không cần mở cả ảnh; giao diện dùng để giữ chỗ khi ảnh chưa tải."""
    p = png_path(document_id, slide_no)
    try:
        head = p.read_bytes()[:24] if p.is_file() else b""
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def pdf_path(doc: Document) -> Path | None:
    src = Path(doc.file_path)
    if src.suffix.lower() == ".pdf":
        return src if src.is_file() else None
    p = render_dir(doc.id) / f"{src.stem}.pdf"
    return p if p.is_file() else None


def _norm(word: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFC", word).lower())


def find_rects(page: pymupdf.Page, text: str) -> tuple[list, bool]:
    """So khớp theo từ (bỏ qua hoa/thường, dấu câu, xuống dòng, NFC/NFD) giữa câu trích và chữ trên trang.

    Trả (các hình chữ nhật cần tô - mỗi dòng một hình, có khớp gần như trọn câu hay không).
    Khớp dưới một nửa số từ thì coi như không tìm thấy để tránh tô nhầm."""
    words = [w for w in page.get_text("words") if _norm(w[4])]
    page_toks = [_norm(w[4]) for w in words]
    ev = [t for t in (_norm(x) for x in (text or "").split()) if t]
    if not ev or not page_toks:
        return [], False
    min_block = min(MIN_BLOCK_WORDS, len(ev))
    blocks = [b for b in SequenceMatcher(None, page_toks, ev, autojunk=False).get_matching_blocks()
              if b.size >= min_block]
    matched = sum(b.size for b in blocks)
    if matched < MIN_COVERAGE * len(ev):
        return [], False
    lines: dict[tuple, pymupdf.Rect] = {}
    for b in blocks:
        for w in words[b.a:b.a + b.size]:
            key = (w[5], w[6])                      # (block, line)
            r = pymupdf.Rect(w[:4])
            lines[key] = lines[key] | r if key in lines else r
    return list(lines.values()), matched >= EXACT_COVERAGE * len(ev)


@lru_cache(maxsize=128)
def _render(pdf: str, slide_no: int, highlight: str, dpi: int) -> bytes:
    with pymupdf.open(pdf) as doc:
        page = doc[slide_no - 1]
        rects, _ = find_rects(page, highlight)
        if rects:
            annot = page.add_highlight_annot(rects)
            annot.set_colors(stroke=HIGHLIGHT_COLOR)
            annot.update()
        return page.get_pixmap(dpi=dpi).tobytes("png")


def clear_cache() -> None:
    """Bỏ ảnh đã render trong bộ nhớ (gọi khi xoá tài liệu)."""
    _render.cache_clear()


def slide_image(doc: Document, slide_no: int, highlight: str | None = None) -> bytes | None:
    """PNG của slide; có `highlight` thì render lại từ PDF và tô vàng đoạn khớp."""
    png = png_path(doc.id, slide_no)
    pdf = pdf_path(doc)
    if highlight and pdf:
        return _render(str(pdf), slide_no, highlight.strip(), get_config().ingestion.render_dpi)
    if png.is_file():
        return png.read_bytes()
    if pdf:
        return _render(str(pdf), slide_no, "", get_config().ingestion.render_dpi)
    return None


def locate(doc: Document, text: str, candidates: list[int]) -> int | None:
    """Tìm slide (trong các slide ứng viên) chứa câu trích; ưu tiên slide khớp nguyên câu."""
    pdf = pdf_path(doc)
    if not pdf or not text:
        return None
    partial = None
    with pymupdf.open(pdf) as d:
        for n in candidates:
            if not 1 <= n <= d.page_count:
                continue
            rects, exact = find_rects(d[n - 1], text)
            if exact:
                return n
            if rects and partial is None:
                partial = n
    return partial
