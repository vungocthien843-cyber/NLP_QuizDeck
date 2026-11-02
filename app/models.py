"""ORM ánh xạ bảng trong migrations/001_init.sql. File SQL là nguồn chuẩn của schema."""
from datetime import datetime

from pgvector.sqlalchemy import SPARSEVEC, Vector
from sqlalchemy import BigInteger, Boolean, Computed, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EMBED_DIM = 1024
SPARSE_DIM = 250002


def _created_at():
    return mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int | None]
    source_type: Mapped[str] = mapped_column(Text, default="slide")
    filename: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    session_no: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created_at()


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    source_type: Mapped[str] = mapped_column(Text)
    session_no: Mapped[int | None]
    slide_no: Mapped[int | None]
    slide_end: Mapped[int | None]
    page_no: Mapped[int | None]
    chapter_no: Mapped[int | None]
    title: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    vlm_caption: Mapped[str | None] = mapped_column(Text)
    embed_text: Mapped[str] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    sparse = mapped_column(SPARSEVEC(SPARSE_DIM), nullable=True)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', embed_text)", persisted=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    session_no: Mapped[int | None]
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB)          # {"A": "...", ...} sau khi xáo
    answer: Mapped[str] = mapped_column(String(1))
    rationales: Mapped[dict] = mapped_column(JSONB)       # {"A": "vì sao đúng/sai", ...}
    explanation: Mapped[str | None] = mapped_column(Text)
    bloom_level: Mapped[str | None] = mapped_column(Text)
    source_chunk_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    status: Mapped[str] = mapped_column(Text)             # accepted | rejected
    validation: Mapped[dict | None] = mapped_column(JSONB)
    stem_embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created_at()


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int | None]
    scope: Mapped[dict] = mapped_column(JSONB)
    num_questions: Mapped[int]
    bloom_mix: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    position: Mapped[int]


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    user_name: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict] = mapped_column(JSONB)          # {question_id: "A"}
    score: Mapped[float | None] = mapped_column(Float)
    submitted_at: Mapped[datetime] = _created_at()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id"))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    created_at: Mapped[datetime] = _created_at()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(Text)               # user | assistant
    content: Mapped[str] = mapped_column(Text)
    cited_chunk_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    created_at: Mapped[datetime] = _created_at()
