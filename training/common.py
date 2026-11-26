"""Tiện ích dùng chung cho phần huấn luyện. Không phụ thuộc vào app/, để chạy độc lập trên Kaggle."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

# Cùng danh sách cấm với app/generation/validator.py (v1): câu có phương án kiểu này bị loại khỏi dữ liệu.
BANNED_PHRASES = (
    "tất cả đều đúng", "tất cả đều sai", "tất cả các đáp án", "tất cả các phương án", "cả a, b, c", "cả ba đáp án",
    "cả ba phương án", "không có đáp án nào", "không có phương án nào", "all of the above", "none of the above",
    "cả a và b", "cả b và c", "cả a và c", "tất cả các ý trên", "cả 3 đáp án", "cả 3 phương án",
)

# Từ dừng tiếng Việt (theo âm tiết) + một số từ tiếng Anh. Chỉ dùng để KHÔNG phạt những từ này trong unlikelihood.
STOPWORDS = frozenset("""
và của là có các những được trong cho với không một này đó khi từ để thì mà như về theo cũng đã sẽ đang
rất nhiều ít hơn nhất ra vào lên xuống tại do bởi nên vì nếu hay hoặc thì là bị sự việc cái con người
nó họ chúng ta tôi bạn ông bà anh chị em ở trên dưới giữa sau trước nào gì ai đâu bao sao vậy thế
những mỗi mọi cả chỉ còn lại đến tới qua lúc nay đây kia ấy thuộc gồm bằng phải nhau mình
the a an of to in on for and or is are was were be by with as at from that this it its
""".split())

LETTERS = "ABCDEFGH"
_DASHES = re.compile(r"[‐-―\-]")
_WS = re.compile(r"\s+")


def nfc(s: str | None) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", s or "")).strip()


def syllables(s: str) -> list[str]:
    """Tách theo âm tiết (tiếng Việt viết cách âm tiết), chữ thường, bỏ dấu câu; gạch nối → khoảng trắng."""
    s = _DASHES.sub(" ", nfc(s).lower())
    return re.findall(r"\w+", s)


def normalize_text(s: str) -> str:
    return " ".join(syllables(s))


def key_recall(candidate: str, answer: str) -> float:
    """Tỉ lệ âm tiết của đáp án đúng có mặt trong ứng viên. ≥ 0,95 → coi như chép đáp án (K5)."""
    k, c = syllables(answer), set(syllables(candidate))
    return sum(t in c for t in k) / len(k) if k else 0.0


def has_banned(text: str) -> bool:
    t = nfc(text).lower()
    return any(p in t for p in BANNED_PHRASES)


def neg_terms(answer: str, question: str) -> list[str]:
    """Âm tiết nội dung của đáp án đúng, không có trong câu hỏi, không phải từ dừng (tập A⁻ của K1)."""
    q = set(syllables(question))
    out, seen = [], set()
    for t in syllables(answer):
        if t in q or t in STOPWORDS or t.isdigit() or len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def format_input(question: str, answer: str, context: str) -> str:
    """Câu hỏi và đáp án đặt trước để khi cắt bớt chỉ mất phần đuôi ngữ cảnh."""
    return f"câu hỏi: {question} | đáp án: {answer} | ngữ cảnh: {context}"


def stable_hash(s: str, n: int = 12) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def bucket(key: str) -> float:
    """Số trong [0, 1) cố định theo key — dùng để chia tập ổn định giữa các lần chạy."""
    return int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) / 0x100000000


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: str | Path, rows) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def file_hash(paths) -> str:
    h = hashlib.sha1()
    for p in sorted(str(p) for p in paths):
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()[:16]
