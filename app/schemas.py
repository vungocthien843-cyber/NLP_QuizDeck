"""Pydantic schema: dữ liệu vào/ra của API và định dạng output LLM khi sinh MCQ."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

BloomLevel = Literal["remember", "understand", "apply"]
Letter = Literal["A", "B", "C", "D"]
MIN_QUIZ_QUESTIONS = 10
MAX_QUIZ_QUESTIONS = 50


# ---------- Output LLM sinh MCQ (mục 7) ----------
class GeneratedOption(BaseModel):
    text: str
    is_correct: bool
    rationale: str


class GeneratedMCQ(BaseModel):
    key_point: str = ""                 # ý kiến thức được kiểm tra (LLM viết trước khi ra câu hỏi)
    evidence: str                       # câu trích NGUYÊN VĂN từ ngữ cảnh chứng minh đáp án đúng
    stem: str
    options: list[GeneratedOption] = Field(min_length=4, max_length=4)
    explanation: str
    bloom_level: BloomLevel
    source_chunk_ids: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_options(self) -> "GeneratedMCQ":
        self.stem = self.stem.strip()
        for o in self.options:
            o.text, o.rationale = o.text.strip(), o.rationale.strip()
        if not self.stem or any(not o.text for o in self.options):
            raise ValueError("stem hoặc phương án bị rỗng")
        if sum(o.is_correct for o in self.options) != 1:
            raise ValueError("phải có đúng 1 phương án đúng")
        texts = [o.text.strip().lower() for o in self.options]
        if len(set(texts)) != 4:
            raise ValueError("các phương án bị trùng nhau")
        return self


# ---------- Documents ----------
class DocumentOut(BaseModel):
    id: int
    filename: str
    session_no: int | None
    status: str
    error: str | None = None
    num_chunks: int = 0
    num_accepted: int = 0
    num_rejected: int = 0
    num_slides: int = 0


class SlideInfo(BaseModel):
    slide_no: int
    title: str | None = None
    notes: str | None = None
    width: int | None = None      # kích thước ảnh PNG của slide
    height: int | None = None


class SlidesOut(BaseModel):
    document_id: int
    num_slides: int
    slides: list[SlideInfo]


class GenerateMoreIn(BaseModel):
    slide_from: int | None = None
    slide_to: int | None = None
    n: int | None = None


# ---------- Search ----------
class Scope(BaseModel):
    document_ids: list[int] | None = None
    session_nos: list[int] | None = None
    slide_from: int | None = None
    slide_to: int | None = None
    chapter_nos: list[int] | None = None


class SearchIn(BaseModel):
    query: str
    scope: Scope = Scope()
    k: int | None = None
    rerank: bool | None = None
    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"


class RetrievedChunk(BaseModel):
    chunk_id: int
    session_no: int | None
    slide_no: int | None
    slide_end: int | None
    title: str | None
    raw_text: str
    image_path: str | None
    score: float
    dense_score: float | None = None


# ---------- Quizzes & attempts ----------
class QuizCreateIn(BaseModel):
    scope: Scope
    n: int = Field(ge=MIN_QUIZ_QUESTIONS, le=MAX_QUIZ_QUESTIONS)
    bloom_mix: dict[BloomLevel, float] | None = None


class QuizQuestionOut(BaseModel):
    question_id: int
    position: int
    bloom_level: str | None = None
    stem: str
    options: dict[Letter, str]          # không kèm answer / rationales / explanation


class QuizOut(BaseModel):
    quiz_id: int
    num_requested: int
    num_questions: int
    questions: list[QuizQuestionOut]


class AttemptIn(BaseModel):
    quiz_id: int
    user_name: str | None = None
    answers: dict[int, Letter]          # question_id -> đáp án chọn


class AttemptOut(BaseModel):
    attempt_id: int
    num_correct: int
    num_questions: int
    score_10: float


class SourceOut(BaseModel):
    chunk_id: int
    document_id: int
    session_no: int | None
    slide_no: int | None
    slide_end: int | None = None
    title: str | None
    raw_text: str
    image_url: str | None


class ReviewItem(BaseModel):
    question_id: int
    stem: str
    options: dict[Letter, str]
    chosen: Letter | None
    answer: Letter
    is_correct: bool
    rationales: dict[Letter, str]
    explanation: str | None
    bloom_level: str | None = None
    sources: list[SourceOut]
    evidence: str | None = None             # câu trích nguyên văn từ slide chứng minh đáp án đúng
    evidence_document_id: int | None = None
    evidence_slide_no: int | None = None    # slide chứa câu trích (đã dò trên PDF)


class ReviewOut(BaseModel):
    attempt_id: int
    score_10: float
    items: list[ReviewItem]


# ---------- Chat ----------
class ChatIn(BaseModel):
    """question_id / attempt_id: câu trắc nghiệm đính kèm vào tin nhắn này (có thể đổi theo từng tin)."""
    message: str
    conversation_id: int | None = None
    attempt_id: int | None = None
    question_id: int | None = None
