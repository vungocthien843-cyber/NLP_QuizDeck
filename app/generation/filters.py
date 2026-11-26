"""Bước 4–5 của pipeline v2: lọc ứng viên đáp án nhiễu. Không xoá ứng viên bị loại, chỉ ghi rejected_at
để lưu lại và phân tích sau.

  form  cụm bị cấm ("tất cả đều đúng"...), rỗng, mẫu rác của ViT5 ("không có thông tin..."), độ dài lệch quá
        nhiều so với đáp án đúng hoặc ngắn tới mức validator sẽ loại cả câu (correct_too_long)
  copy  chép đáp án đúng: phủ ≥ copy_threshold âm tiết của đáp án đúng (K5, ngưỡng 0,95 như Chung et al. 2020)
  nli   ngữ cảnh chứng minh ứng viên là đúng (entailment ≥ entail_threshold) → không còn "chắc chắn sai".
        NLI chấm đáp án đúng thấp → không hiểu câu, bỏ qua. NLI định loại quá nửa số ứng viên (bão hoà, thường vì
        nhiều ứng viên là diễn đạt lại đáp án đúng) → loại từ điểm cao xuống, giữ lại nli_saturated_keep ứng viên.
  form  còn loại đáp án nhiễu dùng từ tuyệt đối ("luôn", "chỉ có", "mọi"...) khi đáp án đúng không dùng: dấu hiệu
        để đoán là sai (Haladyna et al. 2002).
"""
import re
import unicodedata

from app.config import get_config
from app.generation.validator import BANNED_PHRASES, CORRECT_LEN_RATIO, CORRECT_LEN_SLACK_WORDS

_DASHES = re.compile(r"[‐-―\-]")
# Mẫu rác ViT5 học từ VSMRC (câu không trả lời được) — không bao giờ là phương án hợp lý trên slide
_JUNK = re.compile(r"không có thông tin|không được đề cập|không đề cập|đoạn văn")
# Từ tuyệt đối. "chỉ" đứng riêng là từ tuyệt đối, nhưng "chỉ số/chỉ tiêu/chỉ ra..." là từ thường.
ABSOLUTE = re.compile(
    r"(?<!\w)(luôn luôn|luôn|không bao giờ|chẳng bao giờ|tất cả|mọi|duy nhất|hoàn toàn|bất kể|"
    r"chỉ(?!\s+(?:số|tiêu|định|ra|dẫn|thị|mục|thông|huy|đạo|báo|trích|rõ))(?!\w))(?!\w)")


def has_absolute(text: str) -> bool:
    return bool(ABSOLUTE.search(unicodedata.normalize("NFC", text or "").lower()))


def syllables(s: str) -> list[str]:
    s = _DASHES.sub(" ", unicodedata.normalize("NFC", s or "").lower())
    return re.findall(r"\w+", s)


def normalize_key(s: str) -> str:
    return " ".join(syllables(s))


def key_recall(candidate: str, answer: str) -> float:
    k, c = syllables(answer), set(syllables(candidate))
    return sum(t in c for t in k) / len(k) if k else 0.0


def length_ok(candidate: str, answer: str, ratio: float) -> bool:
    lc, la = len(candidate.split()), len(answer.split())
    if not la * (1 - ratio) - 3 <= lc <= la * (1 + ratio) + 3:
        return False
    # Khớp luật correct_too_long của validator: nếu mọi phương án sai đều đạt mức này thì câu không bị loại
    return lc >= min(la / CORRECT_LEN_RATIO, la - CORRECT_LEN_SLACK_WORDS)


def is_junk(text: str) -> bool:
    return bool(_JUNK.search(unicodedata.normalize("NFC", text).lower())) or len(re.sub(r"\W", "", text)) < 2


def apply_rule_filters(cands: list, answer: str) -> None:
    """form + copy. Ghi copy_score cho mọi ứng viên."""
    cfg = get_config().distractor
    key_absolute = has_absolute(answer)
    for c in cands:
        c.copy_score = round(key_recall(c.text, answer), 3)
        low = c.text.lower()
        if not c.text.strip() or any(p in low for p in BANNED_PHRASES) or is_junk(c.text):
            c.rejected_at = "form"
        elif not key_absolute and has_absolute(c.text):
            c.rejected_at = "form"
        elif c.copy_score >= cfg.copy_threshold:
            c.rejected_at = "copy"
        elif not length_ok(c.text, answer, cfg.length_ratio):
            # phương án dài/ngắn lệch hẳn các phương án khác là dấu hiệu dễ đoán (luật đồng dạng)
            c.rejected_at = "form"


def statement(stem: str, option: str) -> str:
    """Giả thuyết cho NLI: 'câu hỏi + phương án' viết thành một mệnh đề."""
    return f"{stem.rstrip(' ?')}: {option}"


def nli_premise(evidence: str, chunk_text: str, stem: str, answer: str) -> str:
    """evidence + các câu của slide liên quan nhất tới câu hỏi/đáp án. Không đưa cả slide: phần mô tả hình
    (logo, bố cục...) làm NLI 'chứng minh' được cả những phương án lạc đề."""
    from app.local_models import select_context

    n = get_config().distractor.nli_context_words
    return f"{evidence}\n{select_context(chunk_text, stem, answer, max_words=n)}"


def apply_nli_filter(cands: list, stem: str, answer: str, premise: str) -> tuple[float | None, str]:
    """Ghi entail_prob, loại ứng viên bị entailment. Trả (xác suất entailment của chính đáp án đúng, chế độ):
    chế độ = applied | skip_key_low (NLI không thấy cả đáp án đúng được chứng minh) | saturated (NLI chấm quá nửa
    phương án là đúng: loại từ điểm cao xuống, giữ lại nli_saturated_keep ứng viên) | none (không còn ứng viên)."""
    from app.local_models import get_nli

    alive = [c for c in cands if c.rejected_at is None]
    if not alive:
        return None, "none"
    cfg = get_config().distractor
    probs = get_nli().entailment(premise, [statement(stem, answer)] + [statement(stem, c.text) for c in alive])
    key_p, cand_p = probs[0], probs[1:]
    for c, p in zip(alive, cand_p, strict=True):
        c.entail_prob = round(p, 4)
    hits = [p >= cfg.entail_threshold for p in cand_p]
    if key_p < cfg.nli_min_key_entail:
        mode = "skip_key_low"
    elif sum(hits) > cfg.nli_max_reject_share * len(alive):
        mode = "saturated"
        n_reject = min(sum(hits), max(len(alive) - cfg.nli_saturated_keep, 0))
        for c in sorted(alive, key=lambda c: -c.entail_prob)[:n_reject]:
            c.rejected_at = "nli"
    else:
        mode = "applied"
        for c, hit in zip(alive, hits, strict=True):
            if hit:
                c.rejected_at = "nli"
    return round(key_p, 4), mode
