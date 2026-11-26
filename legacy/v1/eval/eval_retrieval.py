"""Tầng 1 – Retrieval (mục 11): Hit@5, Recall@5, MRR@10, nDCG@10 theo nhóm, theo phần (tay / LLM).

Golden set: eval/golden_set/*.jsonl, mỗi dòng:
  {"id": "q001", "query": "...", "group": "vi_vi|en_en|mixed|vi_en|image",
   "part": "manual|llm", "relevant_chunk_ids": [12, 40], "reference_answer": "...", "out_of_scope": false}

Chạy: python -m eval.eval_retrieval --configs dense sparse tsvector hybrid hybrid_rerank
"""
import argparse


def load_golden(path: str) -> list[dict]:
    raise NotImplementedError


def run_config(name: str, golden: list[dict], k: int = 10) -> dict[str, dict[str, float]]:
    """Trả run theo định dạng ranx: {query_id: {chunk_id: score}}."""
    raise NotImplementedError


def evaluate(golden: list[dict], runs: dict[str, dict]) -> None:
    """ranx.evaluate cho từng cấu hình; tách theo group và part; ghi eval/results/retrieval_*.csv."""
    raise NotImplementedError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default="eval/golden_set")
    parser.add_argument("--configs", nargs="+", default=["dense", "sparse", "hybrid", "hybrid_rerank"])
    parser.add_argument("--no-vlm", action="store_true", help="Embed lại embed_text bỏ vlm_caption (trong bộ nhớ)")
    args = parser.parse_args()
    raise NotImplementedError(args)


if __name__ == "__main__":
    main()
