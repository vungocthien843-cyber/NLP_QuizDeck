"""Viết lại câu hỏi nối tiếp thành câu độc lập (mục 9 – bước 2). Prompt: app/prompts/chat_rewrite.txt."""
import logging

from app.config import get_config
from app.llm_client import acomplete
from app.models import ChatMessage
from app.prompts import render

log = logging.getLogger(__name__)


async def rewrite_question(message: str, history: list[ChatMessage]) -> str:
    """Lượt đầu (history rỗng) trả nguyên message; lỗi thì cũng dùng nguyên message."""
    if not history:
        return message
    lines = "\n".join(f"{'Người học' if m.role == 'user' else 'Trợ giảng'}: {m.content}" for m in history)
    prompt = render("chat_rewrite", history=lines, message=message)
    try:
        result = await acomplete("chat_rewriter", [{"role": "user", "content": prompt}],
                                 temperature=get_config().llm.temperature_judge)
    except Exception:
        log.warning("Viết lại câu hỏi lỗi, dùng câu gốc", exc_info=True)
        return message
    return result.text.strip() or message
