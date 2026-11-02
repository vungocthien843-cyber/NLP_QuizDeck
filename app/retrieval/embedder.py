"""bge-m3 chạy local: dense 1024 chiều + sparse (lexical weights)."""
import threading
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from pgvector import SparseVector

from app.config import get_config, get_settings
from app.models import SPARSE_DIM


@dataclass
class EmbeddingResult:
    dense: np.ndarray
    sparse: SparseVector


def load_flag_model(cls, name: str):
    """FlagEmbedding đổi tên tham số thiết bị giữa các bản (`devices` ≥ 1.3, `device` bản cũ)."""
    settings = get_settings()
    try:
        return cls(name, use_fp16=settings.embedding_use_fp16, devices=settings.embedding_device)
    except TypeError:
        return cls(name, use_fp16=settings.embedding_use_fp16, device=settings.embedding_device)


class Embedder:
    def __init__(self) -> None:
        from FlagEmbedding import BGEM3FlagModel  # import chậm, chỉ nạp khi cần

        self.batch_size = get_config().ingestion.embed_batch_size
        self.model = load_flag_model(BGEM3FlagModel, get_config().models.embedding)
        self._lock = threading.Lock()  # được gọi từ nhiều thread (BackgroundTasks, asyncio.to_thread)

    def encode(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        with self._lock:
            out = self.model.encode(texts, batch_size=self.batch_size, return_dense=True, return_sparse=True)
        return [
            # lexical_weights có key là token id dạng chuỗi → ép int; SparseVector tự xử lý chỉ số 1-based
            EmbeddingResult(dense=np.asarray(d), sparse=SparseVector({int(k): float(v) for k, v in w.items()}, SPARSE_DIM))
            for d, w in zip(out["dense_vecs"], out["lexical_weights"], strict=True)
        ]

    def encode_one(self, text: str) -> EmbeddingResult:
        return self.encode([text])[0]


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()
