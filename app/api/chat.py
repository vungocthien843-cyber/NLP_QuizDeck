"""Chatbot RAG có trích dẫn, stream câu trả lời (mục 9)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.access import can_view, visible_ids
from app.auth.deps import can_view_user, require_user
from app.chat.answerer import answer_stream, get_or_create_conversation
from app.db import get_db
from sqlalchemy import func, select

from app.models import Attempt, ChatMessage, Chunk, Conversation, Document, Question, User
from app.schemas import ChatCitation, ChatIn, ChatMessageOut, ConversationOut

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_user)])


@router.post("")
def post_chat(body: ChatIn, db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> StreamingResponse:
    # Câu trắc nghiệm / bài làm đính kèm phải thuộc phạm vi người hỏi được xem
    if body.question_id is not None:
        q = db.get(Question, body.question_id)
        if q is None or not can_view(user, db.get(Document, q.document_id)):
            raise HTTPException(404, "Không tìm thấy câu hỏi")
    if body.attempt_id is not None:
        att = db.get(Attempt, body.attempt_id)
        if att is None or not can_view_user(user, att.user_id):
            raise HTTPException(404, "Không tìm thấy bài làm")
    conversation = get_or_create_conversation(db, body.conversation_id, body.attempt_id, body.question_id,
                                              user.id if user else None, bool(user and user.is_admin))
    # Trợ lý chỉ truy hồi trong tài liệu người hỏi được xem (thư viện chung + slide riêng của mình)
    allowed = visible_ids(db, user)
    # Stream NDJSON: {"type":"token","text":...} ... rồi {"type":"done","citations":[...]}
    return StreamingResponse(
        answer_stream(conversation.id, body.message, body.question_id, body.attempt_id, allowed),
        media_type="application/x-ndjson",
        headers={"X-Conversation-Id": str(conversation.id)},
    )


_CITE = re.compile(r"\[(\d+)\]")


def _own_conversation(db: Session, user: User | None, conversation_id: int) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or (user is not None and not user.is_admin and conv.user_id != user.id):
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> list[ConversationOut]:
    """20 hội thoại gần nhất của người đang đăng nhập (tiêu đề = câu hỏi đầu tiên)."""
    if user is None:
        return []
    convs = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                       .order_by(Conversation.created_at.desc()).limit(20)).all()
    out = []
    for c in convs:
        msgs = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == c.id).order_by(ChatMessage.id)).all()
        if not msgs:
            continue
        first = next((m.content for m in msgs if m.role == "user"), "Hội thoại")
        out.append(ConversationOut(conversation_id=c.id, title=first[:80], created_at=c.created_at.isoformat(),
                                   n_messages=len(msgs)))
    return out


@router.get("/conversations/{conversation_id}", response_model=list[ChatMessageOut])
def get_conversation(conversation_id: int, db: Session = Depends(get_db),
                     user: User | None = Depends(require_user)) -> list[ChatMessageOut]:
    """Tin nhắn của một hội thoại. Số trích dẫn [n] khớp lại với chunk đã lưu (theo thứ tự tăng dần như lúc trả lời)."""
    _own_conversation(db, user, conversation_id)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(ChatMessage.id)).all()
    chunk_ids = {cid for m in msgs for cid in (m.cited_chunk_ids or [])}
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))} if chunk_ids else {}
    names = {i: f for i, f in db.execute(select(Document.id, Document.filename).where(
        Document.id.in_({c.document_id for c in chunks.values()}))).all()} if chunks else {}
    out = []
    for m in msgs:
        cites: list[ChatCitation] = []
        ids = list(m.cited_chunk_ids or [])
        nums = sorted({int(x) for x in _CITE.findall(m.content)})
        if m.role == "assistant" and ids and len(nums) >= len(ids):
            nums = nums[: len(ids)]
            for n, cid in zip(nums, ids):
                c = chunks.get(cid)
                if c and can_view(user, db.get(Document, c.document_id)):
                    cites.append(ChatCitation(n=n, chunk_id=c.id, document_id=c.document_id, session_no=c.session_no,
                                              slide_no=c.slide_no, slide_end=c.slide_end, title=c.title,
                                              filename=(names.get(c.document_id) or "").rsplit(".", 1)[0] or None))
        out.append(ChatMessageOut(role=m.role, content=m.content, citations=cites))
    return out
