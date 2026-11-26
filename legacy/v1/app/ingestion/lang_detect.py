"""Nhận diện ngôn ngữ chunk: vi | en | mixed (dùng để phân tích kết quả theo nhóm)."""
from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

MIXED_MIN_SHARE = 0.2   # ngôn ngữ phụ chiếm >= 20% số ký tự thì coi là mixed
CODES = {Language.VIETNAMESE: "vi", Language.ENGLISH: "en"}


@lru_cache
def _detector():
    return LanguageDetectorBuilder.from_languages(*CODES).build()


def detect_lang(text: str) -> str | None:
    if not text.strip():
        return None
    shares = dict.fromkeys(CODES, 0)
    for seg in _detector().detect_multiple_languages_of(text):
        shares[seg.language] += seg.end_index - seg.start_index
    total = sum(shares.values())
    if total == 0:
        lang = _detector().detect_language_of(text)
        return CODES.get(lang) if lang else None
    minor = min(shares.values()) / total
    if minor >= MIXED_MIN_SHARE:
        return "mixed"
    return CODES[max(shares, key=shares.get)]
