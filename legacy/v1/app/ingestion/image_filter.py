"""Lọc ảnh rác trước khi gọi VLM (mục 5): ảnh quá nhỏ và ảnh lặp ở nhiều slide (logo, nền template)."""
from collections import Counter

from app.config import get_config
from app.ingestion.slide_parser import SlidePage


def filter_images(pages: list[SlidePage]) -> None:
    """Đặt `keep=False` cho ảnh có area_ratio < image_min_area_ratio
    hoặc cùng digest xuất hiện ở >= image_repeat_ratio số slide."""
    cfg = get_config().ingestion
    n = len(pages)
    counts = Counter(d for p in pages for d in {img.digest for img in p.images})
    for p in pages:
        for img in p.images:
            too_small = img.area_ratio < cfg.image_min_area_ratio
            repeated = n >= 4 and counts[img.digest] / n >= cfg.image_repeat_ratio
            img.keep = not (too_small or repeated)


def needs_vlm(page: SlidePage) -> bool:
    """Gọi VLM khi còn ảnh sau lọc hoặc slide có ít hơn vlm_min_words từ."""
    return any(img.keep for img in page.images) or page.word_count < get_config().ingestion.vlm_min_words
