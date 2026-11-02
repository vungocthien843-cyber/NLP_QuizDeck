"""Tiện ích dùng chung cho các bước đánh giá MCQ: đường dẫn, snapshot, CSV, khoảng tin cậy, gọi judge."""
import csv
import json
import math
import random
import sys
from pathlib import Path

from app.config import get_config
from app.generation.common import LETTERS, format_options
from app.llm_client import JSON_MODE, acomplete, parse_json
from app.prompts import render

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

SNAPSHOT = DATA_DIR / "snapshot.jsonl"
SNAPSHOT_CHUNKS = DATA_DIR / "snapshot_chunks.jsonl"
SNAPSHOT_META = DATA_DIR / "snapshot_meta.json"
SHEET_PILOT = DATA_DIR / "phieu_cham_thu.csv"
SHEET_RATER1 = DATA_DIR / "phieu_cham_nguoi1.csv"
SHEET_RATER2 = DATA_DIR / "phieu_cham_nguoi2.csv"
SAMPLE_KEY = DATA_DIR / "khoa_mau.csv"        # ma_cau → question_id, status. Người chấm không mở file này.
SHEET_FINAL = DATA_DIR / "phieu_chot.csv"
JUDGE_RUNS = RESULTS_DIR / "judge.jsonl"

BINARY_CRITERIA = ("dung_kien_thuc", "mot_dap_an_dung", "evidence_chung_minh", "tu_dung_duoc")
SCALE_CRITERIA = ("ro_rang", "phuong_an_sai_hop_ly", "dung_muc_bloom")
DEFAULT_SEED = 42


def fail(message: str) -> None:
    print(f"LỖI: {message}", file=sys.stderr)
    raise SystemExit(1)


# ---------- Snapshot ----------
def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_questions() -> list[dict]:
    if not SNAPSHOT.exists():
        fail("chưa có snapshot. Chạy trước: python -m eval.mcq.step1_snapshot")
    return _read_jsonl(SNAPSHOT)


def load_chunks() -> dict[int, dict]:
    return {c["id"]: c for c in _read_jsonl(SNAPSHOT_CHUNKS)}


def load_meta() -> dict:
    return json.loads(SNAPSHOT_META.read_text(encoding="utf-8"))


def rule_of(validation: dict) -> str | None:
    """Luật đã loại câu này, None nếu câu qua hết các bước."""
    for step in ("source_ids", "form", "evidence", "duplicate"):
        result = validation.get(step)
        if result and not result["passed"]:
            return result["details"].get("rule") or result["reason"]
    return None


# ---------- CSV ----------
def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    """utf-8-sig để Excel đọc đúng tiếng Việt."""
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    """Đọc cả file Excel đã lưu lại: Excel có thể đổi dấu phân cách thành ';' và đổi bảng mã."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1258", errors="replace")
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    return list(csv.DictReader(text.splitlines(keepends=True), delimiter=delimiter))


# ---------- Thống kê ----------
def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Khoảng tin cậy Wilson 95% cho một tỉ lệ; dùng được cả khi mẫu nhỏ hoặc tỉ lệ gần 0, 1."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# ---------- Judge ----------
def context_of(question: dict, chunks: dict[int, dict]) -> list[dict]:
    """Các chunk nguồn của câu hỏi. DB không lưu chunk bổ trợ mà câu hỏi không dùng, nên không dựng lại được."""
    return [chunks[i] for i in question["source_chunk_ids"] if i in chunks]


def format_judge_context(context: list[dict]) -> str:
    return "\n\n".join(c["embed_text"] for c in context)


async def ask_judge(stem: str, options: dict[str, str], context: list[dict], rng: random.Random) -> dict:
    """Judge làm lại câu hỏi. Xáo phương án trước khi hỏi, kết quả đổi lại về chữ cái gốc.
    choice: A–D theo chữ cái gốc, hoặc NONE khi ngữ cảnh không đủ để trả lời."""
    original = list(options)
    rng.shuffle(original)
    shown = {LETTERS[i]: options[letter] for i, letter in enumerate(original)}
    prompt = render("answerability", context=format_judge_context(context), stem=stem, options=format_options(shown))
    result = await acomplete("judge_independent", [{"role": "user", "content": prompt}],
                             temperature=get_config().llm.temperature_judge, response_format=JSON_MODE)
    data = parse_json(result.text)
    choice = str(data.get("choice", "")).strip().upper()
    if choice not in shown and choice != "NONE":
        raise ValueError(f"judge trả lựa chọn không hợp lệ: {choice!r}")
    return {
        "choice": "NONE" if choice == "NONE" else original[LETTERS.index(choice)],
        "reason": data.get("reason", ""),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost_usd": result.cost_usd,
        "model": result.model,
    }
