"""Chatbot RAG có trích dẫn, stream câu trả lời (mục 9)."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.chat.answerer import answer_stream, get_or_create_conversation
from app.db import get_db
from app.schemas import ChatIn

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
def post_chat(body: ChatIn, db: Session = Depends(get_db)) -> StreamingResponse:
    conversation = get_or_create_conversation(db, body.conversation_id, body.attempt_id, body.question_id)
    # Stream NDJSON: {"type":"token","text":...} ... rồi {"type":"done","citations":[...]}
    return StreamingResponse(
        answer_stream(conversation.id, body.message, body.question_id, body.attempt_id),
        media_type="application/x-ndjson",
        headers={"X-Conversation-Id": str(conversation.id)},
    )
