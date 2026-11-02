"""Chatbot RAG có trích dẫn (mục 9). Prompt: app/prompts/chat_system.txt."""
import asyncio
import json
import re
from collections.abc import AsyncIterator

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chat.rewriter import rewrite_question
from app.config import get_config
from app.db import SessionLocal
from app.generation.common import format_options, slide_label
from app.llm_client import astream
from app.models import Attempt, ChatMessage, Chunk, Conversation, Document, Question
from app.prompts import render
from app.retrieval.hybrid import retrieve_detailed
from app.schemas import Scope

REDIRECT_TEXT = "Vui lòng đặt câu hỏi đúng với nội dung môn học để mình hỗ trợ tốt nhất nhé."
_CITATION = re.compile(r"\[(\d+)\]")


def get_or_create_conversation(
    db: Session, conversation_id: int | None, attempt_id: int | None, question_id: int | None
) -> Conversation:
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(404, "Không tìm thấy hội thoại")
        return conversation
    conversation = Conversation(attempt_id=attempt_id, question_id=question_id)
    db.add(conversation)
    db.commit()
    return conversation


def _event(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _history(db: Session, conversation_id: int, turns: int) -> list[ChatMessage]:
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(turns * 2)
    )
    return list(reversed(list(rows)))


def _mcq_block(db: Session, question_id: int | None, attempt_id: int | None) -> tuple[str, Question | None]:
    """Thông tin câu trắc nghiệm được đính kèm vào tin nhắn (chế độ hỏi về một câu cụ thể)."""
    if not question_id or not (q := db.get(Question, question_id)):
        return "", None
    chosen = None
    if attempt_id and (attempt := db.get(Attempt, attempt_id)):
        chosen = attempt.answers.get(str(q.id))
    rationales = "\n".join(f"{k}: {v}" for k, v in q.rationales.items())
    block = (
        f"CÂU TRẮC NGHIỆM NGƯỜI HỌC ĐANG HỎI:\n{q.stem}\n{format_options(q.options)}\n"
        f"Người học chọn: {chosen or '(chưa chọn)'} · Đáp án đúng: {q.answer}\n"
        f"Lý do từng phương án:\n{rationales}\n"
    )
    return block, q


def _doc_names(db: Session, chunks: list[Chunk]) -> dict[int, str]:
    """Tên file (bỏ đuôi) của các tài liệu chứa chunk, dùng để ghi nguồn."""
    ids = {c.document_id for c in chunks}
    rows = db.execute(select(Document.id, Document.filename).where(Document.id.in_(ids))).all() if ids else []
    return {i: (f or "").rsplit(".", 1)[0] for i, f in rows}


def _build_context(db: Session, query: str, question: Question | None) -> tuple[list[Chunk], float | None]:
    """Chế độ câu hỏi: chunk nguồn của câu đứng đầu, lọc theo tài liệu của câu. Khử trùng, tối đa max_context_chunks."""
    cfg = get_config().chat
    scope = Scope(document_ids=[question.document_id]) if question else None
    result = retrieve_detailed(db, query, scope)
    pinned_ids = list(question.source_chunk_ids) if question else []
    ordered = list(dict.fromkeys([*pinned_ids, *(c.chunk_id for c in result.chunks)]))[: cfg.max_context_chunks]
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(ordered)))}
    return [chunks[i] for i in ordered if i in chunks], result.best_dense


def _offtopic_replies(db: Session, conversation_id: int) -> int:
    """Số lượt trả lời trước đó không trích dẫn tài liệu nào (xã giao hoặc ngoài phạm vi)."""
    return db.scalar(
        select(func.count()).select_from(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id, ChatMessage.role == "assistant",
            func.coalesce(func.cardinality(ChatMessage.cited_chunk_ids), 0) == 0,
        )
    )


def _save_turn(db: Session, conversation_id: int, user_text: str, answer: str, cited: list[int]) -> None:
    db.add_all([
        ChatMessage(conversation_id=conversation_id, role="user", content=user_text),
        ChatMessage(conversation_id=conversation_id, role="assistant", content=answer, cited_chunk_ids=cited),
    ])
    db.commit()


async def answer_stream(conversation_id: int, message: str, question_id: int | None = None,
                        attempt_id: int | None = None) -> AsyncIterator[str]:
    """Mỗi dòng NDJSON:
      {"type": "token", "text": "..."}
      {"type": "done", "citations": [{"n": 1, "chunk_id": 12, "document_id": 3, "session_no": 5,
                                       "slide_no": 12, "slide_end": 12, "title": "..."}]}
    question_id / attempt_id: câu trắc nghiệm đính kèm RIÊNG tin nhắn này (tin sau không đính kèm thì hỏi tự do).
    Tự mở session riêng vì generator chạy sau khi request handler đã trả về."""
    cfg = get_config()
    with SessionLocal() as db:
        history = _history(db, conversation_id, cfg.chat.history_turns)
        mcq_block, question = _mcq_block(db, question_id, attempt_id)
        standalone = await rewrite_question(message, history)
        context, best_dense = await asyncio.to_thread(_build_context, db, standalone, question)

        # Từ chối sớm khi hỏi tự do mà không có đoạn nào đủ liên quan (chế độ câu hỏi luôn có chunk nguồn)
        if not question and (best_dense is None or best_dense < cfg.chat.min_dense_score):
            if _offtopic_replies(db, conversation_id) >= cfg.chat.smalltalk_turns:
                reply = REDIRECT_TEXT
                yield _event(type="token", text=reply)
            else:
                parts = []
                small = [{"role": "system", "content": render("chat_smalltalk", course_name=cfg.course.name)}]
                small += [{"role": m.role, "content": m.content} for m in history]
                small.append({"role": "user", "content": message})
                try:
                    async for delta in astream("chat_answer", small, temperature=cfg.llm.temperature_chat):
                        parts.append(delta)
                        yield _event(type="token", text=delta)
                except Exception as exc:
                    yield _event(type="error", message=f"Lỗi khi gọi LLM: {exc}")
                    return
                reply = "".join(parts)
            _save_turn(db, conversation_id, message, reply, [])
            yield _event(type="done", citations=[])
            return

        names = _doc_names(db, context)
        docs = "\n\n".join(
            f"[{n}] ({names.get(c.document_id, 'Tài liệu')} – Slide {slide_label(c)})\n{c.embed_text}"
            for n, c in enumerate(context, start=1)
        )
        messages = [{"role": "system", "content": render("chat_system", course_name=cfg.course.name)}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        messages.append({"role": "user", "content": f"TÀI LIỆU:\n{docs}\n\n{mcq_block}\nCÂU HỎI: {message}"})

        parts: list[str] = []
        try:
            async for delta in astream("chat_answer", messages, temperature=cfg.llm.temperature_chat):
                parts.append(delta)
                yield _event(type="token", text=delta)
        except Exception as exc:
            yield _event(type="error", message=f"Lỗi khi gọi LLM: {exc}")
            return
        answer = "".join(parts)

        cited_numbers = sorted({int(m) for m in _CITATION.findall(answer) if 1 <= int(m) <= len(context)})
        citations = [
            {"n": n, "chunk_id": context[n - 1].id, "document_id": context[n - 1].document_id,
             "session_no": context[n - 1].session_no, "slide_no": context[n - 1].slide_no,
             "filename": names.get(context[n - 1].document_id),
             "slide_end": context[n - 1].slide_end, "title": context[n - 1].title}
            for n in cited_numbers
        ]
        _save_turn(db, conversation_id, message, answer, [c["chunk_id"] for c in citations])
        yield _event(type="done", citations=citations)
