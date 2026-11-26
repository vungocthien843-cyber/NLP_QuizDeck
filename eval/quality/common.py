"""Tiện ích chung của bộ đánh giá chất lượng câu trắc nghiệm (eval/quality).

Không phụ thuộc vào app/ (chỉ export.py và lớp embedding mới cần app), để chạy được cả ngoài container.
Tách từ: dùng âm tiết (tiếng Việt viết tách âm tiết) và bỏ hư từ. Đặc tả gợi ý underthesea/pyvi; âm tiết đơn giản
hơn và đủ cho các chỉ số đếm token chung (A4, A10) và ROUGE-L (A7, A8).
"""
import json
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
LETTERS = "ABCD"
_DASHES = re.compile(r"[‐-―\-]")

# Hư từ tiếng Việt (âm tiết). Cố ý giữ "không", "chưa" (phủ định đổi nghĩa) và các con số.
STOPWORDS = frozenset("""
và của là các những một có cho được trong với để khi thì này đó kia ấy theo từ đến về như mà nên vì do bởi bị
đã sẽ đang cũng rất hơn nhất lại ra vào trên dưới nào gì sao bao nhiêu hay hoặc nếu thế ở tại bằng qua sau trước
rằng việc cách điều sự cái chiếc thể còn nữa đều vẫn chỉ hết mỗi từng cả nhau ai đâu thôi luôn
""".split())


def load_cfg(path: str | Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def syllables(s: str) -> list[str]:
    return re.findall(r"\w+", _DASHES.sub(" ", nfc(s).lower()))


def content_tokens(s: str) -> list[str]:
    return [t for t in syllables(s) if t not in STOPWORDS]


def words(s: str) -> int:
    return len(nfc(s).split())


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def key_text(item: dict) -> str:
    return item["options"][item["key"]]


def distractors(item: dict) -> list[str]:
    return [t for k, t in item["options"].items() if k != item["key"]]


def lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l_precision(text: str, context: str) -> float:
    """Tỉ lệ âm tiết của text nằm trong chuỗi con chung dài nhất với context: 'text chép từ slide tới đâu'.
    Dùng precision thay F1 vì context dài hơn text hàng chục lần (F1 khi đó gần 0 với mọi phương án)."""
    t = syllables(text)
    return lcs(t, syllables(context)) / len(t) if t else 0.0


def tie_share(values: list[float], key_index: int) -> float:
    """Điểm 1 nếu phương án key có giá trị lớn nhất; hoà thì 1/số phương án hoà (như A1 của đặc tả).
    Nhờ vậy mức ngẫu nhiên đúng bằng 25% cho mọi chỉ số 'key có phải phương án nổi bật nhất không'."""
    top = max(values)
    ties = [i for i, v in enumerate(values) if v == top]
    return 1 / len(ties) if key_index in ties else 0.0
