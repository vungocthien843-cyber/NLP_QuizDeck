"""Dựng chunk từ slide (mục 5 – Chunk): 1 slide = 1 chunk, gộp slide quá ngắn, dựng embed_text."""
from dataclasses import asdict, dataclass

from app.config import get_config
from app.ingestion.slide_parser import SlidePage


@dataclass
class ChunkDraft:
    session_no: int | None
    slide_no: int
    slide_end: int
    title: str | None
    raw_text: str
    notes: str | None
    vlm_caption: str | None
    embed_text: str
    image_path: str | None
    lang: str | None = None

    def to_row(self) -> dict:
        return asdict(self)


def make_embed_text(session_no: int | None, slide_no: int, slide_end: int, title: str | None,
                    raw_text: str, notes: str | None, vlm_caption: str | None) -> str:
    slides = f"{slide_no}–{slide_end}" if slide_end != slide_no else str(slide_no)
    where = f"Buổi {session_no} – Slide {slides}" if session_no else f"Slide {slides}"
    header = f"[{where}] {title or ''}".strip()
    if title:  # tiêu đề đã nằm trong header, bỏ dòng tiêu đề lặp ở đầu text
        lines = raw_text.splitlines()
        raw_text = "\n".join(ln for i, ln in enumerate(lines) if not (i == 0 and ln.strip() == title))
    return "\n".join(p for p in (header, raw_text, notes, vlm_caption) if p)


def _join(*parts: str | None) -> str | None:
    joined = "\n\n".join(p for p in parts if p)
    return joined or None


def _words(page: SlidePage) -> int:
    return len(f"{page.text} {page.notes or ''} {page.vlm_caption or ''}".split())


def build_chunks(pages: list[SlidePage], session_no: int | None) -> list[ChunkDraft]:
    """Slide ngắn (< merge_min_words) cùng tiêu đề với slide trước → gộp vào slide trước.
    Slide ngắn khác tiêu đề (thường là slide mở mục) → gộp vào slide kế tiếp.
    Slide trống hoàn toàn (không chữ, không mô tả hình) → bỏ."""
    min_words = get_config().ingestion.merge_min_words
    groups: list[list[SlidePage]] = []
    pending: list[SlidePage] = []

    for page in pages:
        words = _words(page)
        if words == 0:
            continue
        if words < min_words:
            if groups and not pending and page.title and page.title == groups[-1][-1].title:
                groups[-1].append(page)
            else:
                pending.append(page)
            continue
        groups.append([*pending, page])
        pending = []
    if pending:
        if groups:
            groups[-1].extend(pending)
        else:
            groups.append(pending)

    drafts = []
    for group in groups:
        first, last = group[0], group[-1]
        main = max(group, key=_words)  # ảnh hiển thị lấy từ slide nhiều nội dung nhất
        title = next((p.title for p in group if p.title), None)
        raw_text = _join(*(p.text for p in group)) or ""
        notes = _join(*(p.notes for p in group))
        caption = _join(*(p.vlm_caption for p in group))
        drafts.append(ChunkDraft(
            session_no=session_no,
            slide_no=first.slide_no,
            slide_end=last.slide_no,
            title=title,
            raw_text=raw_text,
            notes=notes,
            vlm_caption=caption,
            embed_text=make_embed_text(session_no, first.slide_no, last.slide_no, title, raw_text, notes, caption),
            image_path=str(main.png_path),
        ))
    return drafts
