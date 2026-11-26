"""Lớp gọi LLM duy nhất của hệ thống (LiteLLM). Tên model lấy theo vai trò trong config.yaml."""
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

import litellm

from app.config import get_config

log = logging.getLogger(__name__)

Role = Literal[
    "vlm", "mcq_generator", "chat_rewriter", "chat_answer", "judge", "judge_independent"
]


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


JSON_MODE = {"type": "json_object"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> dict:
    """Đọc JSON từ output LLM, bỏ ```json ... ``` nếu model lỡ bọc."""
    return json.loads(_FENCE.sub("", text.strip()))


def _model_for(role: Role) -> str:
    model = getattr(get_config().models, role)
    if not model:
        raise ValueError(f"Chưa cấu hình model cho vai trò '{role}' trong config.yaml")
    return model


def _to_result(resp, model: str) -> LLMResult:
    usage = resp.usage
    try:
        cost = litellm.completion_cost(completion_response=resp)
    except Exception:  # model mới chưa có bảng giá trong LiteLLM
        cost = 0.0
    result = LLMResult(
        text=resp.choices[0].message.content or "",
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost_usd=cost,
    )
    log.info("llm model=%s in=%d out=%d cost=%.5f", model, result.prompt_tokens,
             result.completion_tokens, result.cost_usd)
    return result


async def acomplete(
    role: Role,
    messages: list[dict],
    *,
    temperature: float,
    response_format: dict | type | None = None,
) -> LLMResult:
    """Gọi LLM bất đồng bộ. `response_format` nhận Pydantic model để ép structured output."""
    cfg = get_config().llm
    model = _model_for(role)
    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
        timeout=cfg.timeout,
        num_retries=cfg.max_retries,
        **_reasoning_kwargs(),
    )
    return _to_result(resp, model)


def _reasoning_kwargs() -> dict:
    """Model có reasoning (dòng gpt-6) chỉ nhận temperature khác 1 khi reasoning_effort = 'none'."""
    effort = get_config().llm.reasoning_effort
    return {"reasoning_effort": effort} if effort else {}


async def astream(role: Role, messages: list[dict], *, temperature: float) -> AsyncIterator[str]:
    """Stream từng đoạn text (dùng cho chatbot)."""
    cfg = get_config().llm
    resp = await litellm.acompletion(
        model=_model_for(role),
        messages=messages,
        temperature=temperature,
        stream=True,
        timeout=cfg.timeout,
        num_retries=cfg.max_retries,
        **_reasoning_kwargs(),
    )
    async for chunk in resp:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
