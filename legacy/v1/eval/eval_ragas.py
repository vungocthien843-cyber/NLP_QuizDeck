"""Tầng 2 – Chatbot (mục 11): RAGAS (Faithfulness, Answer Relevancy, Context Precision/Recall)
và khả năng từ chối trên câu ngoài phạm vi.

Lưu ý: cấu hình embedding của RAGAS là bge-m3 (mặc định nó gọi embedding OpenAI); judge = models.judge.
Chạy: python -m eval.eval_ragas
"""


def collect_answers(golden: list[dict]) -> list[dict]:
    """Gọi pipeline chatbot cho từng câu (không lưu DB), lấy answer + contexts + dense_score top-1."""
    raise NotImplementedError


def run_ragas(samples: list[dict]) -> dict:
    raise NotImplementedError


def refusal_metrics(samples: list[dict]) -> dict:
    """Tỉ lệ từ chối đúng (out_of_scope) và từ chối nhầm (trong phạm vi); quét ngưỡng min_dense_score."""
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
