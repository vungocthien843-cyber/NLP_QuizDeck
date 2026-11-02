"""Hậu kiểm MCQ bằng luật (mục 7 – bước 4). KHÔNG gọi LLM. Mọi kết quả ghi vào questions.validation.

Thứ tự: source_ids → form → evidence (đều rẻ, chạy đồng bộ). Bước chống trùng (check_duplicate) chạy riêng
trong bank_builder vì cần khoá để hai câu giống nhau sinh song song không cùng lọt.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import mean

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models import EMBED_DIM, Chunk
from app.schemas import GeneratedMCQ

BANNED_PHRASES = (
    "tất cả đều đúng", "tất cả đều sai", "tất cả các đáp án", "tất cả các phương án", "cả a, b, c", "cả ba đáp án",
    "cả ba phương án", "không có đáp án nào", "không có phương án nào", "all of the above", "none of the above",
)
_LETTER_REF = re.compile(r"(?i)\b(đáp án|phương án|lựa chọn|câu|option|answer)\s+[A-D]\b")
_NEGATION = re.compile(r"(?i)\b(không|chẳng|chưa|not)\b")
# Người làm bài không thấy ngữ cảnh, nên câu hỏi không được trỏ tới "ngữ cảnh đã cho", "đoạn trên", "chunk id"...
# Cố ý KHÔNG cấm chữ "ngữ cảnh" / "chunk" đứng riêng: đó là thuật ngữ NLP hợp lệ (từ ngữ cảnh, chunking).
_CONTEXT_REF = re.compile(
    r"(?i)((?:trong|theo|dựa vào|dựa trên|từ) ngữ cảnh (?:trên|dưới|đã cho|được cung cấp|bên trên|này)|"
    r"chunk (?:id|hạt giống|số)|\bid ?= ?\d|hạt giống|đoạn (?:văn |trích |tài liệu )?(?:trên|dưới|đã cho)|"
    r"(?:văn bản|tài liệu|nội dung) (?:trên|dưới|đã cho))"
)

CORRECT_LEN_RATIO = 1.5        # đáp án đúng không dài hơn 1,5 × độ dài TB đáp án sai ...
CORRECT_LEN_SLACK_WORDS = 4    # ... trừ khi chênh không quá 4 từ (tránh loại oan câu ngắn)
ANSWER_IN_STEM_MIN_WORDS = 3   # đáp án đúng (>= 3 từ) xuất hiện nguyên văn trong stem → lộ đáp án
EVIDENCE_MIN_WORDS = 4
EVIDENCE_MIN_COVERAGE = 0.85   # tỉ lệ ký tự của evidence khớp nguyên văn với một chunk trong ngữ cảnh
EVIDENCE_MIN_BLOCK = 8         # chỉ tính các đoạn khớp liên tục >= 8 ký tự


@dataclass
class ValidationResult:
    passed: bool
    reason: str | None = None              # source_ids | form | evidence | duplicate
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "reason": self.reason, "details": self.details}


def normalize(s: str) -> str:
    """NFC (PDF hay trả tiếng Việt dạng NFD), chữ thường, bỏ dấu câu, gộp khoảng trắng."""
    s = unicodedata.normalize("NFC", s or "").lower()
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def _words(s: str) -> int:
    return len(s.split())


def check_source_ids(mcq: GeneratedMCQ, context_ids: set[int], seed_id: int | None = None) -> ValidationResult:
    """source_chunk_ids phải nằm trong ngữ cảnh đã đưa và phải có chunk hạt giống."""
    outside = set(mcq.source_chunk_ids) - context_ids
    if outside:
        return ValidationResult(False, "source_ids", {"rule": "outside_context", "outside": sorted(outside)})
    if seed_id is not None and seed_id not in mcq.source_chunk_ids:
        return ValidationResult(False, "source_ids", {"rule": "seed_missing", "seed_id": seed_id})
    return ValidationResult(True)


def check_form(mcq: GeneratedMCQ) -> ValidationResult:
    """Luật hình thức của một câu trắc nghiệm tốt."""
    for o in mcq.options:
        if any(p in o.text.lower() for p in BANNED_PHRASES):
            return ValidationResult(False, "form", {"rule": "banned_phrase", "option": o.text})
    if len(_NEGATION.findall(mcq.stem)) >= 2:
        return ValidationResult(False, "form", {"rule": "double_negation"})
    if m := _CONTEXT_REF.search(" ".join([mcq.stem, *(o.text for o in mcq.options)])):
        return ValidationResult(False, "form", {"rule": "context_reference", "match": m.group(0)})

    correct = next(o for o in mcq.options if o.is_correct)
    correct_words = _words(correct.text)
    wrong_avg = mean(_words(o.text) for o in mcq.options if not o.is_correct) or 1
    if correct_words > CORRECT_LEN_RATIO * wrong_avg and correct_words - wrong_avg > CORRECT_LEN_SLACK_WORDS:
        return ValidationResult(False, "form", {"rule": "correct_too_long", "correct_words": correct_words,
                                                "wrong_avg_words": round(wrong_avg, 1)})

    correct_norm = normalize(correct.text)
    if _words(correct_norm) >= ANSWER_IN_STEM_MIN_WORDS and correct_norm in normalize(mcq.stem):
        return ValidationResult(False, "form", {"rule": "answer_in_stem"})

    texts = [mcq.stem, mcq.explanation, *(o.text for o in mcq.options), *(o.rationale for o in mcq.options)]
    if any(_LETTER_REF.search(t) for t in texts):
        return ValidationResult(False, "form", {"rule": "letter_reference"})
    return ValidationResult(True)


def evidence_coverage(evidence: str, chunk_text: str) -> float:
    """Tỉ lệ ký tự của evidence khớp NGUYÊN VĂN (theo các đoạn liên tục >= EVIDENCE_MIN_BLOCK) với chunk."""
    ev, ctx = normalize(evidence), normalize(chunk_text)
    if not ev:
        return 0.0
    if ev in ctx:
        return 1.0
    blocks = SequenceMatcher(None, ev, ctx, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks if b.size >= EVIDENCE_MIN_BLOCK) / len(ev)


def check_evidence(mcq: GeneratedMCQ, context: list[Chunk]) -> ValidationResult:
    """Thay cho LLM judge groundedness: evidence (câu trích chứng minh đáp án đúng) phải được trích
    gần như nguyên văn từ một chunk trong ngữ cảnh. Chặn phần lớn trường hợp LLM bịa kiến thức ngoài slide."""
    if _words(normalize(mcq.evidence)) < EVIDENCE_MIN_WORDS:
        return ValidationResult(False, "evidence", {"rule": "too_short"})
    best_id, best = None, 0.0
    for c in context:
        cov = evidence_coverage(mcq.evidence, f"{c.raw_text}\n{c.notes or ''}\n{c.vlm_caption or ''}")
        if cov > best:
            best_id, best = c.id, cov
        if best >= 1.0:
            break
    details = {"coverage": round(best, 3), "chunk_id": best_id}
    if best < EVIDENCE_MIN_COVERAGE:
        return ValidationResult(False, "evidence", {"rule": "not_verbatim", **details})
    return ValidationResult(True, details=details)


def check_duplicate(db: Session, stem_embedding, threshold: float) -> ValidationResult:
    """Cosine(stem + đáp án đúng) với câu accepted (tài liệu còn hoạt động) > threshold → trùng."""
    stmt = text(
        "SELECT q.id, 1 - (q.stem_embedding <=> :e) AS sim FROM questions q "
        "JOIN documents d ON d.id = q.document_id "
        "WHERE q.status = 'accepted' AND d.is_active AND q.stem_embedding IS NOT NULL "
        "ORDER BY q.stem_embedding <=> :e LIMIT 1"
    ).bindparams(bindparam("e", type_=Vector(EMBED_DIM)))
    row = db.execute(stmt, {"e": stem_embedding}).first()
    if row and row.sim > threshold:
        return ValidationResult(False, "duplicate", {"similar_to": row.id, "similarity": round(float(row.sim), 3)})
    return ValidationResult(True, details={"max_similarity": round(float(row.sim), 3) if row else None})


def validate(mcq: GeneratedMCQ, context: list[Chunk], seed_id: int | None = None) -> tuple[ValidationResult, dict]:
    """Chạy lần lượt, dừng ở bước trượt đầu tiên. Trả (kết quả cuối, dict chi tiết từng bước để lưu JSONB)."""
    report: dict = {}
    context_ids = {c.id for c in context}
    steps = (
        ("source_ids", lambda: check_source_ids(mcq, context_ids, seed_id)),
        ("form", lambda: check_form(mcq)),
        ("evidence", lambda: check_evidence(mcq, context)),
    )
    for name, step in steps:
        result = step()
        report[name] = result.as_dict()
        if not result.passed:
            return result, report
    return ValidationResult(True), report


# ---------- Phản hồi đưa vào prompt khi sinh lại ----------
_FEEDBACK = {
    "outside_context": "source_chunk_ids chứa id không có trong NGỮ CẢNH. Chỉ ghi id của các chunk đã đưa.",
    "seed_missing": "source_chunk_ids phải có id của chunk hạt giống, và câu hỏi phải xoay quanh chunk đó.",
    "banned_phrase": "Không dùng phương án kiểu \"tất cả đều đúng/sai\" hoặc \"không có phương án nào\".",
    "double_negation": "Câu hỏi đang có phủ định kép. Viết lại ở dạng khẳng định hoặc chỉ một phủ định.",
    "context_reference": "Người làm bài không thấy ngữ cảnh: không viết \"theo ngữ cảnh đã cho\", \"đoạn trên\", \"chunk id\"; "
                         "câu hỏi phải tự đứng được.",
    "correct_too_long": "Đáp án đúng dài hơn hẳn các phương án sai nên dễ đoán. Viết lại để 4 phương án dài "
                        "tương đương (chênh không quá vài từ).",
    "answer_in_stem": "Câu hỏi đang chứa nguyên văn đáp án đúng. Diễn đạt lại để không lộ đáp án.",
    "letter_reference": "Không nhắc chữ cái A/B/C/D ở bất kỳ đâu (thứ tự phương án sẽ được xáo).",
    "too_short": "evidence quá ngắn. Trích nguyên văn 1–2 câu đầy đủ từ NGỮ CẢNH chứng minh đáp án đúng.",
    "not_verbatim": "evidence không khớp nguyên văn với NGỮ CẢNH. Sao chép đúng từng chữ câu trong ngữ cảnh "
                    "chứng minh đáp án đúng; nếu ngữ cảnh không có câu nào như vậy thì đổi sang ý khác có căn cứ.",
    "duplicate": "Câu hỏi trùng ý với một câu đã có trong ngân hàng. Hỏi một khía cạnh khác của chunk hạt giống.",
}


def feedback_for(result: ValidationResult) -> str:
    rule = result.details.get("rule") or result.reason or ""
    return _FEEDBACK.get(rule, f"Câu hỏi trượt bước kiểm tra \"{result.reason}\".")
