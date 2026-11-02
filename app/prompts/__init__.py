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
