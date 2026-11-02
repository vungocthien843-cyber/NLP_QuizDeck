"""bge-reranker-v2-m3 (thí nghiệm, bật bằng retrieval.rerank trong config.yaml)."""
import threading
from functools import lru_cache

from app.config import get_config
from app.retrieval.embedder import load_flag_model


class Reranker:
    def __init__(self) -> None:
        from FlagEmbedding import FlagReranker

        self.model = load_flag_model(FlagReranker, get_config().models.reranker)
        self._lock = threading.Lock()

    def rerank(self, query: str, candidates: list[tuple[int, str]]) -> list[tuple[int, float]]:
        """candidates: [(chunk_id, embed_text)] → [(chunk_id, score)] giảm dần."""
        if not candidates:
            return []
        with self._lock:
            scores = self.model.compute_score([[query, t] for _, t in candidates], normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        return sorted(((cid, float(s)) for (cid, _), s in zip(candidates, scores, strict=True)),
                      key=lambda x: x[1], reverse=True)


@lru_cache
def get_reranker() -> Reranker:
    return Reranker()
