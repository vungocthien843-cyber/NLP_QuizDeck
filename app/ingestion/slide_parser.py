"""Parse slide (mục 5 – Parse): PPTX → PDF bằng LibreOffice, trích text + notes, render PNG."""
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.config import get_config, get_settings

_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*(/\s*\d{1,3})?\s*$")


@dataclass
class SlideImage:
    xref: int
    area_ratio: float          # diện tích ảnh / diện tích trang
    digest: str                # hash nội dung ảnh, dùng phát hiện logo / ảnh nền lặp
    keep: bool = True          # image_filter đặt False nếu là ảnh rác


@dataclass
class SlidePage:
    slide_no: int
    title: str | None
    text: str
    notes: str | None
    png_path: Path
    images: list[SlideImage] = field(default_factory=list)
    vlm_caption: str | None = None

    @property
    def word_count(self) -> int:
        return len(f"{self.text} {self.notes or ''}".split())


def convert_pptx_to_pdf(pptx_path: Path, out_dir: Path) -> Path:
    """Gọi `soffice --headless --convert-to pdf`. Mỗi lần dùng một profile tạm để chạy song song được."""
    soffice = get_settings().soffice_bin
    if not shutil.which(soffice) and not Path(soffice).is_file():
        raise RuntimeError(f"Không tìm thấy LibreOffice ('{soffice}'). Cài LibreOffice hoặc tải slide dạng PDF.")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
             "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx_path)],
            check=True, capture_output=True, timeout=300,
        )
    pdf_path = out_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.is_file():
        raise RuntimeError("LibreOffice không tạo được file PDF")
    return pdf_path


def read_speaker_notes(pptx_path: Path) -> dict[int, str]:
    """python-pptx: {slide_no: notes}. Bỏ slide ẩn vì LibreOffice không xuất slide ẩn ra PDF."""
    from pptx import Presentation

    notes: dict[int, str] = {}
    slide_no = 0
    for slide in Presentation(str(pptx_path)).slides:
        if slide._element.get("show") == "0":
            continue
        slide_no += 1
        if slide.has_notes_slide:
            text = slide.notes_slide.notes_text_frame.text.strip()
            if text:
                notes[slide_no] = text
    return notes


def _shape_texts(shapes) -> list[tuple[int, int, str]]:
    """Chữ trong các shape (kể cả group, bảng), kèm vị trí (top, left) để sắp theo thứ tự đọc."""
    out = []
    for sh in shapes:
        top, left = int(sh.top or 0), int(sh.left or 0)
        if sh.shape_type == 6:                      # MSO_SHAPE_TYPE.GROUP
            out += _shape_texts(sh.shapes)
        elif getattr(sh, "has_table", False) and sh.has_table:
            rows = [" | ".join(c.text.strip() for c in r.cells) for r in sh.table.rows]
            out.append((top, left, "\n".join(rows)))
        elif sh.has_text_frame and sh.text_frame.text.strip():
            out.append((top, left, sh.text_frame.text.strip()))
    return out


def read_slide_texts(pptx_path: Path) -> dict[int, tuple[str | None, str]]:
    """python-pptx: {slide_no: (tiêu đề, nội dung)} lấy thẳng từ PPTX.

    Dùng thay cho chữ trích từ PDF vì LibreOffice thay font (vd. Calibri → Carlito) có thể làm hỏng lớp chữ
    tiếng Việt trong PDF ("một" thành "m t" + "ộ" rời). Ảnh slide vẫn render từ PDF."""
    from pptx import Presentation
    from pptx.enum.shapes import PP_PLACEHOLDER

    result: dict[int, tuple[str | None, str]] = {}
    slide_no = 0
    for slide in Presentation(str(pptx_path)).slides:
        if slide._element.get("show") == "0":
            continue
        slide_no += 1
        title = None
        for sh in slide.placeholders:
            if sh.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE) and sh.has_text_frame:
                title = " ".join(sh.text_frame.text.split())[:200] or None
                break
        parts = sorted(_shape_texts(slide.shapes))
        text = "\n".join(t for _, _, t in parts)
        result[slide_no] = (title, text.replace("\x0b", "\n"))
    return result


def remove_repeated_lines(pages: list[SlidePage], ratio: float) -> None:
    """Bỏ header/footer: dòng xuất hiện ở >= ratio số slide, và dòng chỉ là số trang."""
    if len(pages) >= 4:
        counts = Counter(line for p in pages for line in {ln.strip() for ln in p.text.splitlines() if ln.strip()})
        repeated = {line for line, c in counts.items() if c / len(pages) >= ratio}
    else:
        repeated = set()
    for p in pages:
        kept = [ln for ln in p.text.splitlines()
                if ln.strip() and ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)]
        p.text = "\n".join(kept)


def _guess_title(page: pymupdf.Page) -> str | None:
    """Tiêu đề = dòng có cỡ chữ lớn nhất nằm ở nửa trên của slide."""
    best_size, best_text = 0.0, None
    limit_y = page.rect.y0 + page.rect.height * 0.5
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text or line["bbox"][1] > limit_y:
                continue
            size = max(span["size"] for span in line["spans"])
            if size > best_size + 0.5:
                best_size, best_text = size, text
    return best_text[:200] if best_text else None


def _extract_images(page: pymupdf.Page) -> list[SlideImage]:
    page_area = page.rect.width * page.rect.height or 1.0
    images = []
    for info in page.get_image_info(hashes=True, xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        digest = info.get("digest")
        images.append(SlideImage(
            xref=info.get("xref", 0),
            area_ratio=min(1.0, area / page_area),
            digest=digest.hex() if isinstance(digest, bytes) else str(info.get("xref")),
        ))
    return images


def parse_slides(file_path: str, document_id: int) -> list[SlidePage]:
    """PyMuPDF: trích text, tiêu đề, danh sách ảnh nhúng; render PNG vào data/renders/{document_id}/."""
    cfg = get_config().ingestion
    src = Path(file_path)
    out_dir = get_settings().render_dir / str(document_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    notes: dict[int, str] = {}
    pptx_texts: dict[int, tuple[str | None, str]] = {}
    if src.suffix.lower() == ".pptx":
        notes = read_speaker_notes(src)
        pptx_texts = read_slide_texts(src)
        pdf_path = convert_pptx_to_pdf(src, out_dir)
    else:
        pdf_path = src

    pages: list[SlidePage] = []
    with pymupdf.open(pdf_path) as pdf:
        for i, page in enumerate(pdf, start=1):
            png_path = out_dir / f"slide_{i:03d}.png"
            page.get_pixmap(dpi=cfg.render_dpi).save(png_path)
            title, text = pptx_texts.get(i, (None, None))
            pages.append(SlidePage(
                slide_no=i,
                title=title or _guess_title(page),
                text=text if text is not None else page.get_text("text").strip(),
                notes=notes.get(i),
                png_path=png_path,
                images=_extract_images(page),
            ))
    remove_repeated_lines(pages, cfg.header_repeat_ratio)
    return pages
