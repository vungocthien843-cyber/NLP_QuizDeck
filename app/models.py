"""ORM ánh xạ bảng trong migrations/001_init.sql và 002_v2.sql. File SQL là nguồn chuẩn của schema."""
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
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_shared: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
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
    pipeline_version: Mapped[str] = mapped_column(Text, default="v1")     # v1 | v2 (002_v2.sql)
    answer_type: Mapped[str | None] = mapped_column(Text)                 # loại đáp án (v2, bước 1)
    selection: Mapped[dict | None] = mapped_column(JSONB)                 # thông tin chọn bộ 3 (v2, bước 6)
    # v3 (003_v3.sql)
    option_meta: Mapped[dict | None] = mapped_column(JSONB)               # chữ cái → {role, source, error_type, candidate_id}
    concept: Mapped[str | None] = mapped_column(Text)                     # ý kiến thức (key_point)
    difficulty_est: Mapped[str | None] = mapped_column(Text)              # easy | medium | hard
    difficulty_elo: Mapped[float] = mapped_column(Float, server_default=text("1200"))
    history: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = _created_at()


class DistractorCandidate(Base):
    """Mọi ứng viên đáp án nhiễu của một câu v2, kể cả bị loại, để phân tích vì sao câu ra như vậy."""
    __tablename__ = "distractor_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)                             # vit5 | llm
    error_type: Mapped[str | None] = mapped_column(Text)
    error_type_self: Mapped[str | None] = mapped_column(Text)            # v3: nhãn LLM tự khai lúc sinh
    copy_score: Mapped[float | None] = mapped_column(Float)
    entail_prob: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    rejected_at: Mapped[str | None] = mapped_column(Text)                 # form | copy | nli | None
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created_at()


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int | None]
    scope: Mapped[dict] = mapped_column(JSONB)
    num_questions: Mapped[int]
    bloom_mix: Mapped[dict | None] = mapped_column(JSONB)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))          # v3
    mode: Mapped[str] = mapped_column(Text, server_default=text("'normal'"))    # normal | difficulty | weakness | auto
    difficulty: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    position: Mapped[int]
    reason: Mapped[dict | None] = mapped_column(JSONB)      # v3: vì sao câu được chọn (chế độ luyện điểm yếu)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    user_name: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict] = mapped_column(JSONB)          # {question_id: "A"}
    score: Mapped[float | None] = mapped_column(Float)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))          # v3
    mode: Mapped[str] = mapped_column(Text, server_default=text("'normal'"))
    submitted_at: Mapped[datetime] = _created_at()


# ---------- v3: người học (003_v3.sql) ----------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)     # 005_auth.sql
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class AuthSession(Base):
    """Phiên đăng nhập phía server (005_auth.sql). Chỉ lưu SHA-256 của mã phiên."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    csrf_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)


class Response(Base):
    """Một dòng cho mỗi câu trả lời: biết người học chọn phương án nào, sai vì hiểu nhầm gì."""
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    chosen: Mapped[str | None] = mapped_column(Text)
    answer_payload: Mapped[dict | None] = mapped_column(JSONB)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("distractor_candidates.id", ondelete="SET NULL"))
    error_type: Mapped[str | None] = mapped_column(Text)
    concept: Mapped[str | None] = mapped_column(Text)
    time_ms: Mapped[int | None]
    created_at: Mapped[datetime] = _created_at()


class MisconceptionStat(Base):
    """Hồ sơ hiểu nhầm: điểm theo (người học, ý kiến thức, loại hiểu nhầm), suy giảm theo thời gian."""
    __tablename__ = "misconception_stats"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    concept: Mapped[str] = mapped_column(Text, primary_key=True)
    error_type: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    n_seen: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Feedback(Base):
    """Mốc 3 (G4): phản hồi của người học về chẩn đoán / lời giải thích (migration 004)."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id"))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created_at()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(Text)               # user | assistant
    content: Mapped[str] = mapped_column(Text)
    cited_chunk_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    created_at: Mapped[datetime] = _created_at()
