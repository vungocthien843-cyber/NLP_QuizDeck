"""Model chạy local của pipeline v2, nạp một lần (lazy) và dùng chung cho mọi request.

- ViT5 fine-tune: sinh ứng viên đáp án nhiễu (K3). Chưa có checkpoint → available() = False, pipeline bỏ nguồn này.
- NLI đa ngôn ngữ: lọc ứng viên mà ngữ cảnh chứng minh là đúng.
- Reranker (bge-reranker-v2-m3) dùng lại app.retrieval.reranker.
"""
import logging
import math
import re
import threading
import unicodedata
import warnings
from pathlib import Path

from app.config import get_config
from app.singleton import thread_safe_cache

log = logging.getLogger(__name__)


# ---- Cắt ngữ cảnh giống hệt lúc huấn luyện (training/prepare_data.select_context) ----
_DASHES = re.compile(r"[‐-―\-]")
_SENT = re.compile(r"(?<=[.!?…;:])\s+|\n+|\s+[•\-–]\s+")
MAX_CTX_WORDS = 300


def _syllables(s: str) -> list[str]:
    return re.findall(r"\w+", _DASHES.sub(" ", unicodedata.normalize("NFC", s or "").lower()))


def select_context(context: str, question: str, answer: str, max_words: int = MAX_CTX_WORDS) -> str:
    """Model được huấn luyện với ngữ cảnh đã rút còn ≤ max_words âm tiết (các câu liên quan nhất tới câu hỏi và
    đáp án, giữ thứ tự gốc). Khi sinh phải cắt y như vậy, nếu không đoạn liên quan có thể bị cắt mất ở 512 token."""
    if len(context.split()) <= max_words:
        return context
    sents = [x.strip() for x in _SENT.split(context) if x and x.strip()]
    keys = {t for t in _syllables(f"{question} {answer}") if len(t) > 1}
    scored = []
    for i, sent in enumerate(sents):
        toks = _syllables(sent)
        scored.append((sum(t in keys for t in toks) / math.sqrt(len(toks) + 1), i, len(sent.split())))
    keep, used = set(), 0
    for _, i, n in sorted(scored, key=lambda t: (-t[0], t[1])):
        if used + n > max_words and keep:
            continue
        keep.add(i)
        used += n
        if used >= max_words:
            break
    return " ".join(x for i, x in enumerate(sents) if i in keep)


def _device() -> str:
    import torch

    want = get_config().distractor.device
    if want == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return want


def format_input(question: str, answer: str, context: str) -> str:
    """Phải giống hệt training/common.format_input — model được huấn luyện với đúng khuôn này."""
    return f"câu hỏi: {question} | đáp án: {answer} | ngữ cảnh: {context}"



def _load_tokenizer(checkpoint: str):
    """AutoTokenizer; bản transformers mới đọc tokenizer T5 lưu bởi bản cũ có thể lỗi (Unigram vocab) nên
    lùi về nạp thẳng tokenizer.json (đã kiểm tra cho ra input_ids giống hệt)."""
    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    try:
        return AutoTokenizer.from_pretrained(checkpoint)
    except Exception as exc:
        log.warning("AutoTokenizer lỗi (%s: %s); nạp thẳng tokenizer.json.", type(exc).__name__, exc)
        return PreTrainedTokenizerFast(tokenizer_file=str(Path(checkpoint) / "tokenizer.json"),
                                       eos_token="</s>", unk_token="<unk>", pad_token="<pad>")


class DistractorGenerator:
    def __init__(self, checkpoint: str) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.device = _device()
        self.tok = _load_tokenizer(checkpoint)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint).to(self.device).eval()
        if self.device == "cuda" and torch.cuda.is_bf16_supported():
            self.model = self.model.to(torch.bfloat16)
        self._lock = threading.Lock()
        self._fallback_warned = False
        log.info("Đã nạp ViT5 sinh đáp án nhiễu từ %s (%s)", checkpoint, self.device)

    @staticmethod
    def _kwargs(decoding: str, n: int) -> dict:
        if decoding == "diverse_beam":
            groups = max(1, min(4, n))
            beams = n + (-n) % groups
            return dict(num_beams=beams, num_beam_groups=groups, diversity_penalty=1.0, num_return_sequences=n)
        if decoding == "beam":
            return dict(num_beams=max(n, 2), num_return_sequences=n)
        return dict(do_sample=True, top_p=0.9, temperature=0.8, num_return_sequences=n)

    def generate(self, question: str, answer: str, context: str, n: int, decoding: str) -> list[str]:
        import torch

        context = select_context(context, question, answer)
        enc = self.tok(format_input(question, answer, context), max_length=512, truncation=True,
                       return_tensors="pt").to(self.device)
        kwargs = self._kwargs(decoding, n)
        with self._lock, torch.no_grad(), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                seqs = self.model.generate(**enc, max_new_tokens=64, **kwargs)
            except (ValueError, TypeError, NotImplementedError) as exc:
                if decoding != "diverse_beam":
                    raise
                if not self._fallback_warned:
                    log.warning("diverse beam search không chạy với bản transformers này (%s); dùng sampling.", exc)
                    self._fallback_warned = True
                seqs = self.model.generate(**enc, max_new_tokens=64, **self._kwargs("sampling", n))
        return [t.strip() for t in self.tok.batch_decode(seqs, skip_special_tokens=True)]


class NLI:
    def __init__(self, name: str) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.device = _device()
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).to(self.device).eval()
        labels = {i: str(l).lower() for i, l in self.model.config.id2label.items()}
        self.entail_idx = next(i for i, l in labels.items() if l.startswith("entail"))
        self._lock = threading.Lock()

    def entailment(self, premise: str, hypotheses: list[str], batch_size: int = 16) -> list[float]:
        """Xác suất entailment của từng giả thuyết với cùng một tiền đề."""
        import torch

        out: list[float] = []
        with self._lock, torch.no_grad():
            for i in range(0, len(hypotheses), batch_size):
                hyp = hypotheses[i:i + batch_size]
                enc = self.tok([premise] * len(hyp), hyp, truncation="only_first", max_length=512, padding=True,
                               return_tensors="pt").to(self.device)
                probs = self.model(**enc).logits.float().softmax(-1)[:, self.entail_idx]
                out += probs.tolist()
        return out


def vit5_available() -> bool:
    return (Path(get_config().distractor.vit5_checkpoint) / "config.json").exists()


@thread_safe_cache
def get_generator() -> DistractorGenerator:
    return DistractorGenerator(get_config().distractor.vit5_checkpoint)


@thread_safe_cache
def get_nli() -> NLI:
    return NLI(get_config().models.nli)
