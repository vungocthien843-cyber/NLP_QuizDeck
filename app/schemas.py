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
    is_shared: bool = True              # true: thư viện môn học; false: slide riêng của người tải lên
    is_mine: bool = False               # người đang đăng nhập là người tải lên
    can_edit: bool = False              # được xóa / sinh thêm câu hỏi / sửa thông tin
    owner_email: str | None = None      # chỉ trả cho quản trị viên


class DocumentPatch(BaseModel):
    session_no: int | None = None
    is_shared: bool | None = None       # chỉ quản trị viên: đưa slide riêng vào thư viện chung (hoặc ngược lại)


class QuotaOut(BaseModel):
    unlimited: bool
    max_docs: int
    used_docs: int
    max_upload_mb: int


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
Difficulty = Literal["easy", "medium", "hard"]


class QuizCreateIn(BaseModel):
    scope: Scope
    n: int = Field(ge=MIN_QUIZ_QUESTIONS, le=MAX_QUIZ_QUESTIONS)
    bloom_mix: dict[BloomLevel, float] | None = None
    difficulty: Difficulty | None = None           # v3 (D5): None = trộn mọi mức
    mode: Literal["normal", "weakness"] = "normal"  # v3 (D6): weakness cần user_id
    user_id: int | None = None


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
    mode: str = "normal"
    difficulty: str | None = None
    notice: str | None = None                      # v3: ví dụ không đủ câu đúng mức khó, chưa có dữ liệu điểm yếu


class AttemptIn(BaseModel):
    quiz_id: int
    user_name: str | None = None
    answers: dict[int, Letter]          # question_id -> đáp án chọn
    user_id: int | None = None          # v3: người học đã đăng nhập bằng mã
    times_ms: dict[int, int] | None = None
    allow_unanswered: bool = False      # hết giờ: nộp cả câu chưa làm (tính là sai, không gắn loại hiểu nhầm)


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
    misconception: dict | None = None       # v3 (D1): chọn sai → {code, ten, chan_doan} của phương án đã chọn


class ReviewOut(BaseModel):
    attempt_id: int
    score_10: float
    items: list[ReviewItem]


# ---------- v3: người học ----------
class LoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=100)


class UserOut(BaseModel):
    user_id: int
    code: str
    display_name: str | None


class WeaknessOut(BaseModel):
    concept: str
    error_type: str
    ten: str | None = None
    chan_doan: str | None = None
    score: float
    n_seen: int


class ProfileOut(BaseModel):
    user_id: int
    n_attempts: int
    n_answered: int
    accuracy: float | None
    weaknesses: list[WeaknessOut]
    by_error_type: dict[str, int]           # số lần chọn sai theo loại hiểu nhầm (mọi thời điểm)
    error_type_names: dict[str, str] = {}   # mã loại hiểu nhầm → tên tiếng Việt (để hiển thị)


# ---------- Chat ----------
class ConversationOut(BaseModel):
    conversation_id: int
    title: str
    created_at: str
    n_messages: int


class ChatCitation(BaseModel):
    n: int
    chunk_id: int
    document_id: int
    session_no: int | None = None
    slide_no: int | None = None
    slide_end: int | None = None
    title: str | None = None
    filename: str | None = None


class ChatMessageOut(BaseModel):
    role: str
    content: str
    citations: list[ChatCitation] = []


class AttemptSummary(BaseModel):
    attempt_id: int
    quiz_id: int
    submitted_at: str
    score_10: float
    num_questions: int
    num_correct: int
    mode: str
    label: str                              # tên các bài trong đề


class ChatIn(BaseModel):
    """question_id / attempt_id: câu trắc nghiệm đính kèm vào tin nhắn này (có thể đổi theo từng tin)."""
    message: str
    conversation_id: int | None = None
    attempt_id: int | None = None
    question_id: int | None = None
