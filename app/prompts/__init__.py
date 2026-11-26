"""Nạp prompt từ file .txt cùng thư mục. Dùng thay thế {tên} thủ công vì prompt có chứa JSON mẫu."""
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")


def render(name: str, **values: object) -> str:
    text = load_prompt(name)
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


# ---------- Loại hiểu nhầm (kế hoạch v3, B1): một nguồn cho prompt sinh, prompt gắn nhãn và lời chẩn đoán ----------
UNCLEAR = "khong_ro"     # nhãn cho phương án sai không thể hiện hiểu nhầm cụ thể nào


@lru_cache
def misconception_types() -> dict[str, dict]:
    import json

    return json.loads((PROMPT_DIR / "misconception_types.json").read_text(encoding="utf-8"))


def error_types_block(with_cues: bool = False) -> str:
    """Danh sách loại hiểu nhầm để chèn vào prompt: '- "mã": mô tả' (kèm dấu hiệu nhận biết nếu with_cues)."""
    lines = []
    for code, t in misconception_types().items():
        line = f'- "{code}": {t["mo_ta"]}'
        if with_cues:
            line += f' (dấu hiệu: {t["dau_hieu"]}; ví dụ: {t["vi_du"]})'
        lines.append(line)
    return "\n".join(lines)


def normalize_error_type(value: object, allow_unclear: bool = False) -> str | None:
    """Mã hợp lệ thì giữ, khong_ro giữ khi allow_unclear, còn lại (LLM tự bịa mã) trả None."""
    code = str(value or "").strip().lower()
    if code in misconception_types():
        return code
    if allow_unclear and code == UNCLEAR:
        return UNCLEAR
    return None
