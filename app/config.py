"""Cấu hình: bí mật và hạ tầng đọc từ .env, tham số thuật toán và tên model đọc từ config.yaml."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# LiteLLM đọc OPENAI_API_KEY từ os.environ, nên nạp .env vào môi trường.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    openai_api_key: str = ""
    config_path: Path = Path("config.yaml")
    data_dir: Path = Path("data")
    max_upload_mb: int = 50
    soffice_bin: str = "soffice"
    log_level: str = "INFO"
    embedding_device: str = "cpu"
    embedding_use_fp16: bool = False

    # ---- Đăng nhập Google (OpenID Connect) + phiên phía server, xem app/auth ----
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_domain: str = "ictu.edu.vn"     # chỉ nhận tài khoản @ictu.edu.vn (rỗng = không giới hạn)
    admin_emails: str = ""                         # email quản trị (tải slide, quản lý ngân hàng), cách nhau dấu phẩy
    public_base_url: str = "http://localhost:8080" # địa chỉ trình duyệt mở (nginx: / = giao diện, /api = API)
    session_secret: str = ""                       # khóa ký cookie tạm của luồng đăng nhập; bắt buộc khi bật đăng nhập
    session_cookie: str = "rq_session"
    session_idle_days: int = 7                     # không hoạt động quá số ngày này thì phải đăng nhập lại
    session_max_days: int = 30                     # hạn tuyệt đối của một phiên
    cookie_secure: bool = True                     # chạy http://localhost vẫn được (trình duyệt coi localhost là an toàn)
    auth_required: bool = False                    # True: mọi API cần đăng nhập (bật khi bỏ giao diện Streamlit)
    # Hạn mức slide sinh viên tự tải (mỗi bài tải lên đều gọi LLM sinh câu hỏi → giới hạn để kiểm soát chi phí)
    student_max_docs: int = 10
    student_max_processing: int = 1

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def render_dir(self) -> Path:
        return self.data_dir / "renders"


class ModelsConfig(BaseModel):
    vlm: str
    mcq_generator: str
    chat_rewriter: str
    chat_answer: str
    judge: str
    judge_independent: str | None = None
    embedding: str = "BAAI/bge-m3"
    reranker: str = "BAAI/bge-reranker-v2-m3"
    nli: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"


class LLMConfig(BaseModel):
    temperature_generate: float = 0.7
    temperature_judge: float = 0.0
    temperature_chat: float = 0.2
    timeout: int = 60
    max_retries: int = 3
    reasoning_effort: str | None = "none"


class IngestionConfig(BaseModel):
    render_dpi: int = 150
    vlm_min_words: int = 30
    image_min_area_ratio: float = 0.05
    image_repeat_ratio: float = 0.3
    header_repeat_ratio: float = 0.5
    merge_min_words: int = 15
    embed_batch_size: int = 16


class RetrievalConfig(BaseModel):
    top_n: int = 20
    k: int = 5
    rrf_k: int = 60
    sparse_backend: Literal["bge", "tsvector"] = "bge"
    rerank: bool = False


class BankConfig(BaseModel):
    questions_per_slide: float = 0.5
    oversample: float = 1.5
    bloom_mix: dict[str, float] = {"remember": 0.4, "understand": 0.4, "apply": 0.2}
    min_seed_words: int = 30
    context_k: int = 2
    concurrency: int = 5
    max_retries: int = 2
    dedup_threshold: float = 0.9
    pipeline: Literal["v1", "v2"] = "v1"     # v1: một lần gọi LLM; v2: 8 bước (xem docs/ke-hoach-v2.md)


class DistractorConfig(BaseModel):
    """Pipeline v2: nguồn ứng viên, bộ lọc và cách chọn bộ 3 đáp án nhiễu."""
    sources: list[Literal["vit5", "llm"]] = ["vit5", "llm"]
    vit5_checkpoint: str = "checkpoints/dg-vit5-stage2/best"
    n_candidates: int = 8                  # số ứng viên ViT5 sinh ra
    max_vit5_keep: int = 6                 # giữ tối đa bao nhiêu ứng viên ViT5 sau khi bỏ trùng
    llm_candidates: int = 3                # số ứng viên kiểu hiểu lầm do LLM sinh
    tag_errors: bool = True                # v3 (B2): gắn loại hiểu nhầm cho mọi ứng viên còn sống trước khi chọn bộ
    min_alive: int = 0                     # v3 (A3): sau lọc còn ít hơn số này ứng viên → sinh bù trước khi chọn (0 = tắt)
    neighbor_concepts: int = 0             # v3 (B3): số khái niệm lân cận (RAG) đưa vào prompt hiểu nhầm (0 = tắt)
    decoding: Literal["diverse_beam", "beam", "sampling"] = "diverse_beam"
    copy_threshold: float = 0.95           # K5: phủ ≥ ngưỡng này âm tiết của đáp án đúng → chép đáp án
    length_ratio: float = 0.4              # độ dài lệch quá ±40% (cộng 3 từ dung sai) so với đáp án đúng → loại
    entail_threshold: float = 0.5          # NLI: ngữ cảnh chứng minh ứng viên đúng với xác suất ≥ ngưỡng → loại
    nli_min_key_entail: float = 0.5        # NLI chấm chính đáp án đúng dưới mức này → NLI không hiểu câu, bỏ qua lọc
    nli_max_reject_share: float = 0.5      # NLI định loại quá tỉ lệ này số ứng viên → bão hoà
    nli_saturated_keep: int = 4            # bão hoà: loại các ứng viên điểm NLI cao nhất, giữ lại bấy nhiêu ứng viên
    nli_context_words: int = 120           # tiền đề NLI = evidence + các câu liên quan nhất, tối đa bấy nhiêu âm tiết
    scorer: Literal["reranker", "llm"] = "reranker"
    selection: Literal["entropy", "entropy_no_delta", "top3", "random"] = "entropy"
    delta: float = 0.15                    # K4: đáp án đúng phải hơn phương án sai mạnh nhất ít nhất δ
    tau: float = 1.0                       # nhiệt độ đổi điểm reranker thành logit
    llm_score_permutations: int = 2        # scorer=llm: số lần xáo thứ tự để triệt thiên lệch vị trí
    refill_rounds: int = 1                 # không bộ nào đạt δ → sinh bù tối đa bấy nhiêu lần
    set_length_ratio: float = 1.5          # bộ 4 phương án (cả key) có max/min số từ > ngưỡng → tránh (0 = tắt)
    avoid_key_convergence: bool = True     # tránh bộ mà key chung nhiều từ với các phương án khác NHẤT (đoán được)
    min_error_types: int = 2               # v3 (B4): bộ 3 phải phủ ≥ bấy nhiêu loại hiểu nhầm khác nhau (0 = tắt)
    # G1 (15/11): v3 làm key thành phương án NGẮN nhất ở 41% câu (mức trung tính 25%) → mẹo "chọn câu ngắn nhất".
    # Bật: mỗi câu rút ngẫu nhiên (theo key) một hạng độ dài mục tiêu 0..3 cho key và ưu tiên bộ đạt hạng đó,
    # nên key ngắn nhất / dài nhất / ở giữa đều ~25%, không tạo mẹo ngược kiểu "chọn câu độ dài trung bình".
    key_length_rank: bool = True
    unclear_penalty: float = 0.3           # v3 (B4): trừ vào entropy của bộ cho mỗi phương án "khong_ro"
    device: str = "auto"                   # auto | cpu | cuda


class ChatConfig(BaseModel):
    history_turns: int = 4
    max_context_chunks: int = 7
    min_dense_score: float = 0.35
    smalltalk_turns: int = 2


class CourseConfig(BaseModel):
    name: str = "Môn học"


class LearnerConfig(BaseModel):
    """v3, nhóm D: cá nhân hoá theo người học."""
    weakness_decay_days: float = 14        # nửa đời của điểm hiểu nhầm (ngày)
    weakness_top_k: int = 5                # số điểm yếu dùng khi tạo đề luyện điểm yếu
    # phân vị điểm độ khó ước lượng chia 3 mức (D4): dưới q1 = hard, trên q2 = easy
    difficulty_quantiles: tuple[float, float] = (1 / 3, 2 / 3)


class AppConfig(BaseModel):
    course: CourseConfig = CourseConfig()
    models: ModelsConfig
    llm: LLMConfig = LLMConfig()
    ingestion: IngestionConfig = IngestionConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    bank: BankConfig = BankConfig()
    distractor: DistractorConfig = DistractorConfig()
    chat: ChatConfig = ChatConfig()
    learner: LearnerConfig = LearnerConfig()


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_config() -> AppConfig:
    raw = get_settings().config_path.read_text(encoding="utf-8")
    return AppConfig(**yaml.safe_load(raw))
