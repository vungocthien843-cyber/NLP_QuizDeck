"""Mô tả slide có hình bằng VLM (mục 5). Prompt: app/prompts/vlm_caption.txt."""
import asyncio
import base64
import logging

from app.config import get_config
from app.ingestion.image_filter import needs_vlm
from app.ingestion.slide_parser import SlidePage
from app.llm_client import acomplete
from app.prompts import render

log = logging.getLogger(__name__)


async def caption_page(page: SlidePage) -> str:
    """Gửi PNG của slide + text đã trích cho model `vlm`, trả về mô tả."""
    b64 = base64.b64encode(page.png_path.read_bytes()).decode()
    prompt = render("vlm_caption", slide_text=page.text or "(không có)")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ],
    }]
    result = await acomplete("vlm", messages, temperature=get_config().llm.temperature_judge)
    return result.text.strip()


async def caption_slides(pages: list[SlidePage]) -> None:
    """Gọi song song (giới hạn concurrency) cho các slide cần VLM. Lỗi một slide không làm hỏng cả file."""
    sem = asyncio.Semaphore(get_config().bank.concurrency)

    async def one(page: SlidePage) -> None:
        async with sem:
            try:
                page.vlm_caption = await caption_page(page) or None
            except Exception:
                log.warning("VLM lỗi ở slide %s, bỏ qua mô tả", page.slide_no, exc_info=True)

    await asyncio.gather(*(one(p) for p in pages if needs_vlm(p)))
