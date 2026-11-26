"""bge-reranker-v2-m3: rerank khi truy hồi (bật bằng retrieval.rerank) và chấm điểm phương án ở pipeline v2."""
import threading

from app.config import get_config
from app.singleton import thread_safe_cache
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


    def scores(self, query: str, texts: list[str], normalize: bool = False) -> list[float]:
        """Điểm thô (logit) của từng cặp (query, text), giữ thứ tự đầu vào. Dùng ở pipeline v2 (K4)."""
        if not texts:
            return []
        with self._lock:
            out = self.model.compute_score([[query, t] for t in texts], normalize=normalize)
        return [float(out)] if isinstance(out, (float, int)) else [float(x) for x in out]


@thread_safe_cache
def get_reranker() -> Reranker:
    return Reranker()
