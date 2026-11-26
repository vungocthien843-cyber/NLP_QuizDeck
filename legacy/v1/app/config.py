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


class ChatConfig(BaseModel):
    history_turns: int = 4
    max_context_chunks: int = 7
    min_dense_score: float = 0.35
    smalltalk_turns: int = 2


class CourseConfig(BaseModel):
    name: str = "Môn học"


class AppConfig(BaseModel):
    course: CourseConfig = CourseConfig()
    models: ModelsConfig
    llm: LLMConfig = LLMConfig()
    ingestion: IngestionConfig = IngestionConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    bank: BankConfig = BankConfig()
    chat: ChatConfig = ChatConfig()


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_config() -> AppConfig:
    raw = get_settings().config_path.read_text(encoding="utf-8")
    return AppConfig(**yaml.safe_load(raw))
