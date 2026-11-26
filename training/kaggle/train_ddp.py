# %% [1] Imports
"""Fine-tune ViT5 sinh đáp án nhiễu tiếng Việt, chạy multi-GPU bằng torchrun.

Kỹ thuật lấy từ Chung et al. 2020 (Findings of EMNLP):
  K1  loss = CE + λ·unlikelihood trên token nội dung của đáp án đúng (khối Loss)
  K2  quét λ: chạy lại script với --set training.lam=<λ> (notebook có cell quét)
  K3  sinh nhiều ứng viên bằng diverse beam search (khối Evaluator, GenerationEvaluator)
  K5  đo tỉ lệ chép đáp án đúng (> 0,95) và BLEU/ROUGE-L đa tham chiếu (khối Evaluator)

Chạy: torchrun --standalone --nproc_per_node=2 train_ddp.py --set training.lam=1.0
"""
import argparse
import contextlib
import csv
import datetime
import json
import math
import os
import re
import sys
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import torch  # noqa: E402
import torch.distributed as dist  # noqa: E402
import torch.nn as nn  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from loguru import logger  # noqa: E402
from torch.distributed import init_process_group  # noqa: E402
from torch.nn.parallel import DistributedDataParallel as DDP  # noqa: E402
from torch.utils.data import DataLoader, Dataset, DistributedSampler  # noqa: E402
from torchmetrics import MeanMetric  # noqa: E402
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, get_linear_schedule_with_warmup  # noqa: E402


# %% [2] Run utils
def generate_run_name(cfg) -> str:
    now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    return f"{now.strftime('%Y%m%d_%H%M')}_{cfg.logging.run_name}"


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    log_dir: Path
    cache_dir: Path
    best_model_dir: Path          # định dạng Hugging Face: API nạp thẳng thư mục này
    best_model_path: Path         # trạng thái của lần lưu tốt nhất (epoch, chỉ số)
    last_checkpoint_path: Path    # đủ để chạy tiếp khi phiên Kaggle bị ngắt

    @classmethod
    def from_cfg(cls, cfg, run_name: str) -> "RunPaths":
        run_dir = Path(cfg.logging.artifact_path) / run_name
        best = run_dir / "best_model"
        return cls(run_dir, run_dir / "logs", run_dir / "cache", best, best / "trainer_state.json",
                   run_dir / "last_checkpoint.pt")

    def mkdirs(self) -> None:
        for d in (self.run_dir, self.log_dir, self.cache_dir, self.best_model_dir):
            d.mkdir(parents=True, exist_ok=True)


def setup_ddp_loguru(env, paths: RunPaths) -> None:
    logger.remove()
    log_file = paths.log_dir / f"run_rank_{env.global_rank}.log"
    fmt = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}"
    if env.is_main_process:
        logger.add(sys.stdout, level="INFO", colorize=True)
    logger.add(log_file, format=fmt, level="DEBUG", rotation="10 MB")


def ddp_setup() -> None:
    """Chỉ khởi tạo process group khi chạy bằng torchrun. Có GPU dùng NCCL, không có (chạy thử) dùng gloo."""
    if "LOCAL_RANK" not in os.environ:
        return
    local_rank = int(os.environ["LOCAL_RANK"])
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        init_process_group(backend="nccl", device_id=torch.device(f"cuda:{local_rank}"))
    else:
        init_process_group(backend="gloo")


# %% [3] RuntimeEnv
@dataclass(frozen=True)
class RuntimeEnv:
    precision: str = "auto"                 # auto | bf16 | fp16 | fp32 (từ TrainingConfig)
    is_distributed: bool = field(init=False)
    local_rank: int = field(init=False)
    global_rank: int = field(init=False)
    world_size: int = field(init=False)
    device: torch.device = field(init=False)
    is_main_process: bool = field(init=False)
    amp_enabled: bool = field(init=False)
    amp_dtype: torch.dtype = field(init=False)

    def __post_init__(self):
        is_dist = dist.is_available() and dist.is_initialized()
        local_rank = int(os.environ.get("LOCAL_RANK", 0))
        cuda = torch.cuda.is_available()
        p = self.precision
        if p == "auto":
            p = "bf16" if cuda and torch.cuda.is_bf16_supported() else "fp16" if cuda else "fp32"
        object.__setattr__(self, "is_distributed", is_dist)
        object.__setattr__(self, "local_rank", local_rank)
        object.__setattr__(self, "global_rank", dist.get_rank() if is_dist else 0)
        object.__setattr__(self, "world_size", dist.get_world_size() if is_dist else 1)
        object.__setattr__(self, "device", torch.device(f"cuda:{local_rank}" if cuda else "cpu"))
        object.__setattr__(self, "is_main_process", self.global_rank == 0)
        object.__setattr__(self, "amp_enabled", cuda and p in ("bf16", "fp16"))
        object.__setattr__(self, "amp_dtype", torch.bfloat16 if p == "bf16" else torch.float16)

    def to_device(self, obj):
        if torch.is_tensor(obj):
            return obj.to(self.device, non_blocking=True)
        if isinstance(obj, dict):
            return {k: self.to_device(v) for k, v in obj.items()}
        return obj


# %% [4] Configs
@dataclass
class DataConfig:
    data_dir: str = "/kaggle/input/vsmrc-dg-processed"
    train_file: str = "stage1_train.jsonl"           # một dòng = (câu hỏi, MỘT đáp án nhiễu)
    dev_file: str = "stage1_dev.jsonl"
    dev_q_file: str = "stage1_dev_q.jsonl"           # một dòng = một câu hỏi, đủ đáp án nhiễu — đo khi sinh
    test_q_files: tuple = ("test_vsmrc_q.jsonl",)
    replay_file: str = ""                            # giai đoạn 2: trộn thêm mẫu giai đoạn 1
    replay_ratio: float = 0.2
    subset: float = 1.0                              # < 1 khi quét λ
    dev_limit: int = 4000                            # số mẫu dev tối đa để tính loss
    gen_eval_limit: int = 300                        # số câu dev sinh thử mỗi epoch (chỉ rank 0)
    max_src_len: int = 512
    max_tgt_len: int = 64
    max_neg: int = 32
    num_workers: int = 2


@dataclass
class ModelConfig:
    model_name: str = "VietAI/vit5-base"
    gradient_checkpointing: bool = False


@dataclass
class TrainingConfig:
    num_train_epochs: int = 3
    batch_size: int = 8                              # mỗi GPU
    gradient_accumulation_steps: int = 2             # batch hiệu dụng = batch_size × accum × số GPU
    learning_rate: float = 1e-4
    weight_decay: float = 0.01
    warmup_ratio: float = 0.05
    max_grad_norm: float = 1.0
    precision: str = "auto"                          # T5 hay NaN ở fp16: gặp thì đặt fp32
    lam: float = 1.0                                 # K1: hệ số unlikelihood
    seed: int = 42
    resume: bool = True                              # có last_checkpoint.pt trong run_dir thì chạy tiếp


@dataclass
class GenerationConfig:
    n_candidates: int = 8
    decoding: str = "diverse_beam"                   # diverse_beam | beam | sampling
    max_new_tokens: int = 64
    batch_size: int = 16


@dataclass
class CallbackConfig:
    monitor: str = "val_total_loss"
    mode: str = "min"
    early_stopping_patience: int = 2
    warmup_epochs: int = 1                           # chưa xét dừng sớm trong số epoch đầu này


@dataclass
class LoggingConfig:
    artifact_path: str = "/kaggle/working/runs"
    run_name: str = "dg_vit5_stage1"
    fixed_run_dir: str = ""                          # đặt tên thư mục cố định để chạy tiếp qua nhiều phiên


@dataclass
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    callbacks: CallbackConfig = field(default_factory=CallbackConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def apply_overrides(self, items: list[str]) -> None:
        """--set training.lam=0.5 data.subset=0.3 ... (giá trị đọc theo kiểu JSON nếu được)."""
        for item in items:
            path, raw = item.split("=", 1)
            section, key = path.split(".")
            obj = getattr(self, section)
            if not hasattr(obj, key):
                raise KeyError(f"không có trường cấu hình {path}")
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            if isinstance(getattr(obj, key), tuple) and isinstance(value, list):
                value = tuple(value)
            setattr(obj, key, value)


@dataclass
class TrainerState:
    epoch: int = 0
    global_step: int = 0
    best_metric: float | None = None
    best_epoch: int = -1
    history: list = field(default_factory=list)


@dataclass
class TrainerControl:
    should_save: bool = False
    should_training_stop: bool = False


# %% [5] Data
# Bài toán sinh văn bản nên không có LABEL_MAPPING / class weights như bài phân lớp:
# "nhãn" là chuỗi đáp án nhiễu, token đệm = -100; token bị phạt của unlikelihood đệm = -1.
_DASHES = re.compile(r"[‐-―\-]")


def syllables(s: str) -> list[str]:
    s = _DASHES.sub(" ", unicodedata.normalize("NFC", s or "").lower())
    return re.findall(r"\w+", s)


def key_recall(candidate: str, answer: str) -> float:
    k, c = syllables(answer), set(syllables(candidate))
    return sum(t in c for t in k) / len(k) if k else 0.0


def format_input(question: str, answer: str, context: str) -> str:
    """Phải giống hệt app/local_models.format_input — API dùng đúng khuôn này khi sinh."""
    return f"câu hỏi: {question} | đáp án: {answer} | ngữ cảnh: {context}"


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class DataProcessor:
    """Đọc JSONL đã chuẩn hoá (training/prepare_data.py), tokenize, dựng tập token bị phạt A⁻ (K1),
    ghi cache .pt. Chỉ rank 0 chạy; các rank khác đợi barrier rồi đọc cache."""

    REQUIRED = ("question", "answer", "distractor", "context")

    def __init__(self, cfg: AppConfig, tokenizer, paths: RunPaths):
        self.cfg, self.tok, self.paths = cfg, tokenizer, paths
        self.special = set(tokenizer.all_special_ids) | set(tokenizer(" ", add_special_tokens=False)["input_ids"])

    def _rows(self, name: str, limit: float | int | None = None, seed: int = 0) -> list[dict]:
        rows = read_jsonl(Path(self.cfg.data.data_dir) / name)
        bad = [i for i, r in enumerate(rows) if any(not r.get(k) for k in self.REQUIRED)]
        if bad:
            logger.warning(f"{name}: bỏ {len(bad)} dòng thiếu trường bắt buộc")
            rows = [r for i, r in enumerate(rows) if i not in set(bad)]
        g = torch.Generator().manual_seed(seed)
        if isinstance(limit, float) and limit < 1.0:
            idx = torch.randperm(len(rows), generator=g)[:max(1, int(len(rows) * limit))]
            rows = [rows[i] for i in idx.tolist()]
        elif isinstance(limit, int) and len(rows) > limit:
            idx = torch.randperm(len(rows), generator=g)[:limit]
            rows = [rows[i] for i in idx.tolist()]
        return rows

    def encode(self, r: dict) -> dict:
        d = self.cfg.data
        enc = self.tok(format_input(r["question"], r["answer"], r["context"]), max_length=d.max_src_len, truncation=True)
        tgt = self.tok(text_target=r["distractor"], max_length=d.max_tgt_len, truncation=True)["input_ids"]
        banned = self.special | set(self.tok(r["question"], add_special_tokens=False)["input_ids"]) | set(tgt)
        neg: list[int] = []
        for term in r.get("neg_terms") or []:
            for i in self.tok(term, add_special_tokens=False)["input_ids"] + self.tok(" " + term, add_special_tokens=False)["input_ids"]:
                if i not in banned and i not in neg:
                    neg.append(i)
        return {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"], "labels": tgt,
                "neg_ids": neg[:d.max_neg]}

    def process(self) -> dict[str, Path]:
        d, seed = self.cfg.data, self.cfg.training.seed
        train = self._rows(d.train_file, d.subset, seed)
        if d.replay_file:
            replay = self._rows(d.replay_file, int(len(train) * d.replay_ratio), seed + 1)
            train += replay
            logger.info(f"Trộn {len(replay)} mẫu replay từ {d.replay_file}")
        dev = self._rows(d.dev_file, d.dev_limit, seed)
        out = {}
        for split, rows in (("train", train), ("dev", dev)):
            encoded = [self.encode(r) for r in rows]
            path = self.paths.cache_dir / f"{split}.pt"
            torch.save(encoded, path)
            out[split] = path
            n_neg = sum(bool(e["neg_ids"]) for e in encoded)
            logger.info(f"{split}: {len(encoded)} mẫu, {n_neg} mẫu có token bị phạt (A⁻ khác rỗng)")
            logger.debug(f"{split} ví dụ: {rows[0]['question']!r} → {rows[0]['distractor']!r} | A⁻={rows[0].get('neg_terms')}")
        return out


class DistractorDataset(Dataset):
    def __init__(self, cache_path: Path):
        self.items = torch.load(cache_path)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int) -> dict:
        return self.items[i]


class Collator:
    def __init__(self, pad_id: int):
        self.pad_id = pad_id

    @staticmethod
    def _pad(seqs: list[list[int]], value: int) -> torch.Tensor:
        n = max((len(s) for s in seqs), default=0)
        return torch.tensor([s + [value] * (n - len(s)) for s in seqs], dtype=torch.long).reshape(len(seqs), n)

    def __call__(self, batch: list[dict]) -> dict:
        return {"input_ids": self._pad([b["input_ids"] for b in batch], self.pad_id),
                "attention_mask": self._pad([b["attention_mask"] for b in batch], 0),
                "labels": self._pad([b["labels"] for b in batch], -100),
                "neg_ids": self._pad([b["neg_ids"] for b in batch], -1)}


# %% [6] Model
def build_model(cfg: AppConfig) -> nn.Module:
    model = AutoModelForSeq2SeqLM.from_pretrained(cfg.model.model_name)
    if cfg.model.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"Model {cfg.model.model_name}: {total / 1e6:.1f}M tham số, {trainable / 1e6:.1f}M huấn luyện được")
    return model


# %% [7] Loss
class UnlikelihoodLoss(nn.Module):
    """K1 (Chung et al. 2020, answer negative loss):
        L = CE + λ · mean_t [ − Σ_{a ∈ A⁻} log(1 − p(a | d_<t, x)) ]
    A⁻ = token nội dung của đáp án đúng, không có trong câu hỏi và trong chính đáp án nhiễu tham chiếu."""

    EPS = 1e-6

    def __init__(self, lam: float):
        super().__init__()
        self.lam = lam

    def forward(self, logits: torch.Tensor, targets: dict) -> tuple[torch.Tensor, dict]:
        labels, neg = targets["labels"], targets.get("neg_ids")
        logits = logits.float()
        mask = (labels != -100).float()
        valid = int(mask.sum().item())
        ce = F.cross_entropy(logits.transpose(1, 2), labels, ignore_index=-100)
        ul = logits.new_zeros(())
        if self.lam > 0 and neg is not None and neg.numel() > 0:
            probs = logits.softmax(-1)
            idx = neg.clamp_min(0).unsqueeze(1).expand(-1, probs.size(1), -1)
            p_neg = probs.gather(-1, idx) * (neg >= 0).unsqueeze(1)
            per_pos = -torch.log((1.0 - p_neg).clamp_min(self.EPS)).sum(-1)
            ul = (per_pos * mask).sum() / mask.sum().clamp_min(1.0)
        loss = ce + self.lam * ul
        return loss, {"total_loss": float(loss.detach()), "ce": float(ce.detach()), "ul": float(ul.detach()),
                      "valid_count": valid}


# %% [8] Callbacks
class Callback:
    def on_epoch_end(self, cfg, state: TrainerState, control: TrainerControl, logs: dict, **kwargs) -> None:
        pass


class CallbackList:
    def __init__(self, callbacks: list[Callback], env: RuntimeEnv):
        self.callbacks, self.env = callbacks, env

    def on_epoch_end(self, cfg, state, control, logs, **kwargs) -> None:
        if not self.env.is_main_process:
            return
        for cb in self.callbacks:
            cb.on_epoch_end(cfg, state, control, logs, **kwargs)


def _improved(value: float, best: float | None, mode: str) -> bool:
    return best is None or (value < best if mode == "min" else value > best)


class ModelCheckpoint(Callback):
    """Chỉ bật cờ should_save khi chỉ số theo dõi tốt hơn; Trainer mới là nơi lưu."""

    def on_epoch_end(self, cfg, state, control, logs, **kwargs):
        value = logs.get(cfg.callbacks.monitor)
        if value is not None and _improved(value, state.best_metric, cfg.callbacks.mode):
            state.best_metric, state.best_epoch = value, state.epoch
            control.should_save = True
            logger.info(f"{cfg.callbacks.monitor} tốt hơn ({value:.4f}) → lưu best_model")


class EarlyStopping(Callback):
    def __init__(self, cfg: AppConfig):
        c = cfg.callbacks
        self.patience, self.warmup = c.early_stopping_patience, c.warmup_epochs
        self.wait, self.best = 0, None
        if self.warmup >= cfg.training.num_train_epochs:
            logger.warning(f"warmup_epochs ({self.warmup}) ≥ num_train_epochs ({cfg.training.num_train_epochs}): "
                           f"EarlyStopping sẽ không bao giờ dừng sớm")

    def on_epoch_end(self, cfg, state, control, logs, **kwargs):
        value = logs.get(cfg.callbacks.monitor)
        if value is None:
            return
        if _improved(value, self.best, cfg.callbacks.mode):
            self.best, self.wait = value, 0
            return
        if state.epoch < self.warmup:
            return
        self.wait += 1
        if self.wait >= self.patience:
            control.should_training_stop = True
            logger.info(f"EarlyStopping: {cfg.callbacks.monitor} không cải thiện sau {self.patience} epoch")


class CSVLogger(Callback):
    def __init__(self, paths: RunPaths):
        self.path = paths.log_dir / "training_logs.csv"
        self.columns: list[str] | None = None
        if self.path.exists():                  # chạy tiếp: giữ cột cũ
            with self.path.open(encoding="utf-8") as f:
                self.columns = next(csv.reader(f), None)

    def on_epoch_end(self, cfg, state, control, logs, **kwargs):
        row = {"epoch": state.epoch, "global_step": state.global_step, **logs}
        if self.columns is None:
            self.columns = list(row)
            with self.path.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(self.columns)
        with self.path.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([row.get(c, "") for c in self.columns])


# %% [9] BaseTrainer + DistractorGenTrainer
class BaseTrainer(ABC):
    def __init__(self, cfg: AppConfig, env: RuntimeEnv, model: nn.Module, loss_fn: nn.Module, train_loader,
                 val_loader, paths: RunPaths, callbacks: CallbackList, evaluator, gen_evaluator, tokenizer):
        self.cfg, self.env, self.paths, self.callbacks = cfg, env, paths, callbacks
        self.loss_fn, self.train_loader, self.val_loader = loss_fn, train_loader, val_loader
        self.evaluator, self.gen_evaluator, self.tokenizer = evaluator, gen_evaluator, tokenizer
        model = model.to(env.device)
        self.model = DDP(model, device_ids=[env.local_rank] if env.device.type == "cuda" else None) \
            if env.is_distributed else model
        self.optimizer, self.scheduler = self.configure_optimizers()
        self.scaler = torch.amp.GradScaler("cuda", enabled=env.amp_enabled and env.amp_dtype == torch.float16)
        self.state, self.control = TrainerState(), TrainerControl()
        if cfg.training.resume and paths.last_checkpoint_path.exists():
            self.load_checkpoint()

    @property
    def unwrapped(self) -> nn.Module:
        return self.model.module if isinstance(self.model, DDP) else self.model

    @abstractmethod
    def training_step(self, batch: dict) -> tuple[torch.Tensor, dict]: ...

    @abstractmethod
    def evaluation_step(self, batch: dict) -> tuple[torch.Tensor, dict]: ...

    @abstractmethod
    def configure_optimizers(self): ...

    @staticmethod
    def _flatten_dict(d: dict, prefix: str = "") -> dict:
        out = {}
        for k, v in d.items():
            k = "e2e" if k == "end_to_end" else k
            key = f"{prefix}_{k}" if prefix else k
            if isinstance(v, dict):
                out.update(BaseTrainer._flatten_dict(v, key))
            else:
                out[key] = v
        return out

    def _train_epoch(self) -> dict:
        self.model.train()
        self.evaluator.reset()
        accum = self.cfg.training.gradient_accumulation_steps
        self.optimizer.zero_grad(set_to_none=True)
        n = len(self.train_loader)
        for i, batch in enumerate(self.train_loader):
            batch = self.env.to_device(batch)
            last_micro = (i + 1) % accum == 0 or i + 1 == n
            sync = self.model.no_sync() if (isinstance(self.model, DDP) and not last_micro) else contextlib.nullcontext()
            with sync:
                loss, loss_dict = self.training_step(batch)
                self.scaler.scale(loss / accum).backward()
            self.evaluator.update(loss_dict)
            if last_micro:
                self.scaler.unscale_(self.optimizer)
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.training.max_grad_norm)
                self.scaler.step(self.optimizer)
                self.scaler.update()
                self.scheduler.step()
                self.optimizer.zero_grad(set_to_none=True)
                self.state.global_step += 1
                if self.state.global_step % 50 == 0:
                    logger.debug(f"[rank {self.env.global_rank}] step {self.state.global_step} "
                                 f"loss={loss_dict['total_loss']:.4f} ce={loss_dict['ce']:.4f} ul={loss_dict['ul']:.4f}")
        return self.evaluator.compute()

    @torch.no_grad()
    def _eval_epoch(self) -> dict:
        self.model.eval()
        self.evaluator.reset()
        for batch in self.val_loader:
            _, loss_dict = self.evaluation_step(self.env.to_device(batch))
            self.evaluator.update(loss_dict)
        metrics = self.evaluator.compute()
        if self.env.is_main_process and self.gen_evaluator is not None:
            metrics["gen"] = self.gen_evaluator.evaluate(self.unwrapped, limit=self.cfg.data.gen_eval_limit)
        return metrics

    def fit(self) -> TrainerState:
        start = self.state.epoch
        for epoch in range(start, self.cfg.training.num_train_epochs):
            self.state.epoch = epoch
            if isinstance(getattr(self.train_loader, "sampler", None), DistributedSampler):
                self.train_loader.sampler.set_epoch(epoch)
            train = self._train_epoch()
            val = self._eval_epoch()
            logs = self._flatten_dict({"train": train, "val": val})
            stop = torch.zeros(1, device=self.env.device)
            if self.env.is_main_process:
                logger.info(f"Epoch {epoch} - train_loss {logs['train_total_loss']:.4f} - val_loss {logs['val_total_loss']:.4f}"
                            f" - val_ul {logs['val_ul']:.4f} - val_gen_rouge_l {logs.get('val_gen_rouge_l', float('nan')):.2f}"
                            f" - val_gen_copy_rate_all {logs.get('val_gen_copy_rate_all', float('nan')):.4f}")
                self.control = TrainerControl()
                self.callbacks.on_epoch_end(self.cfg, self.state, self.control, logs)
                self.state.history.append({"epoch": epoch, **logs})
                if self.control.should_save:
                    self.save_best(logs)
                stop[0] = float(self.control.should_training_stop)
            self.state.epoch = epoch + 1
            self.save_checkpoint()
            if self.env.is_distributed:
                dist.broadcast(stop, src=0)
            if stop.item():
                break
        return self.state

    def save_best(self, logs: dict) -> None:
        """Lưu định dạng Hugging Face để API (app/local_models) nạp thẳng thư mục best_model."""
        self.unwrapped.save_pretrained(self.paths.best_model_dir)
        self.tokenizer.save_pretrained(self.paths.best_model_dir)
        self.paths.best_model_path.write_text(json.dumps(
            {"epoch": self.state.epoch, "best_metric": self.state.best_metric, "monitor": self.cfg.callbacks.monitor,
             "logs": logs, "config": asdict(self.cfg)}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def save_checkpoint(self) -> None:
        if not self.env.is_main_process:
            return
        torch.save({"model": self.unwrapped.state_dict(), "optimizer": self.optimizer.state_dict(),
                    "scheduler": self.scheduler.state_dict(), "scaler": self.scaler.state_dict(),
                    "state": asdict(self.state)}, self.paths.last_checkpoint_path)

    def load_checkpoint(self) -> None:
        ck = torch.load(self.paths.last_checkpoint_path, map_location=self.env.device, weights_only=False)
        self.unwrapped.load_state_dict(ck["model"])
        self.optimizer.load_state_dict(ck["optimizer"])
        self.scheduler.load_state_dict(ck["scheduler"])
        self.scaler.load_state_dict(ck["scaler"])
        self.state = TrainerState(**ck["state"])
        logger.info(f"Chạy tiếp từ {self.paths.last_checkpoint_path} (epoch {self.state.epoch}, "
                    f"step {self.state.global_step})")


class DistractorGenTrainer(BaseTrainer):
    def _forward(self, batch: dict) -> tuple[torch.Tensor, dict]:
        with torch.autocast(self.env.device.type, dtype=self.env.amp_dtype, enabled=self.env.amp_enabled):
            out = self.model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
                             labels=batch["labels"])
        return self.loss_fn(out.logits, {"labels": batch["labels"], "neg_ids": batch["neg_ids"]})

    def training_step(self, batch):
        return self._forward(batch)

    def evaluation_step(self, batch):
        return self._forward(batch)

    def configure_optimizers(self):
        t = self.cfg.training
        no_decay = {id(p) for n, p in self.unwrapped.named_parameters() if p.ndim < 2 or "norm" in n.lower()}
        params = [p for p in self.unwrapped.parameters() if p.requires_grad]
        groups = [{"params": [p for p in params if id(p) not in no_decay], "weight_decay": t.weight_decay},
                  {"params": [p for p in params if id(p) in no_decay], "weight_decay": 0.0}]
        optimizer = torch.optim.AdamW(groups, lr=t.learning_rate)
        steps = math.ceil(len(self.train_loader) / t.gradient_accumulation_steps) * t.num_train_epochs
        scheduler = get_linear_schedule_with_warmup(optimizer, int(steps * t.warmup_ratio), steps)
        return optimizer, scheduler


# %% [10] Evaluator
class LossEvaluator:
    """Trung bình có trọng số (valid_count) của total_loss / ce / ul; MeanMetric tự đồng bộ qua DDP."""

    def __init__(self, env: RuntimeEnv):
        self.metrics = {k: MeanMetric().to(env.device) for k in ("total_loss", "ce", "ul")}

    def reset(self) -> None:
        for m in self.metrics.values():
            m.reset()

    def update(self, loss_dict: dict) -> None:
        w = max(loss_dict["valid_count"], 1)
        for k, m in self.metrics.items():
            m.update(torch.tensor(loss_dict[k]), weight=w)

    def compute(self) -> dict:
        out = {}
        for k, m in self.metrics.items():
            v = float(m.compute())
            out[k] = 0.0 if math.isnan(v) else round(v, 5)
        return out


def _ngrams(toks, n):
    return Counter(tuple(toks[i:i + n]) for i in range(len(toks) - n + 1))


def corpus_bleu(hyps, refs, max_n=4) -> dict:
    match, total, hl, rl = [0] * max_n, [0] * max_n, 0, 0
    for h, rs in zip(hyps, refs):
        hl += len(h)
        rl += min((abs(len(r) - len(h)), len(r)) for r in rs)[1] if rs else 0
        for n in range(1, max_n + 1):
            maxref = Counter()
            for r in rs:
                maxref |= _ngrams(r, n)
            match[n - 1] += sum(min(c, maxref[g]) for g, c in _ngrams(h, n).items())
            total[n - 1] += max(len(h) - n + 1, 0)
    bp = 1.0 if hl > rl else math.exp(1 - rl / max(hl, 1))
    out, log_sum = {}, 0.0
    for n in range(1, max_n + 1):
        p = match[n - 1] / total[n - 1] if total[n - 1] else 0.0
        log_sum += math.log(p) if p > 0 else float("-inf")
        out[f"bleu_{n}"] = round(100 * bp * math.exp(log_sum / n), 2) if log_sum > float("-inf") else 0.0
    return out


def rouge_l(h, r, beta=1.2) -> float:
    if not h or not r:
        return 0.0
    prev = [0] * (len(r) + 1)
    for x in h:
        cur = [0]
        for j, y in enumerate(r):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    lcs = prev[-1]
    if lcs == 0:
        return 0.0
    p, rec = lcs / len(h), lcs / len(r)
    return (1 + beta ** 2) * p * rec / (rec + beta ** 2 * p)


class GenerationEvaluator:
    """Sinh n ứng viên/câu (K3) rồi đo theo Chung et al. 2020 (K5). Chỉ chạy trên rank 0."""

    def __init__(self, cfg: AppConfig, env: RuntimeEnv, tokenizer, q_file: Path):
        self.cfg, self.env, self.tok = cfg, env, tokenizer
        self.rows = read_jsonl(q_file) if q_file.exists() else []

    def _kwargs(self, decoding: str) -> dict:
        n = self.cfg.generation.n_candidates
        if decoding == "diverse_beam":
            g = max(1, min(4, n))
            return dict(num_beams=n + (-n) % g, num_beam_groups=g, diversity_penalty=1.0, num_return_sequences=n)
        if decoding == "beam":
            return dict(num_beams=max(n, 2), num_return_sequences=n)
        return dict(do_sample=True, top_p=0.9, temperature=0.8, num_return_sequences=n)

    @torch.no_grad()
    def generate(self, model, rows: list[dict]) -> list[list[str]]:
        g, n, out = self.cfg.generation, self.cfg.generation.n_candidates, []
        model.eval()
        for i in range(0, len(rows), g.batch_size):
            batch = rows[i:i + g.batch_size]
            enc = self.tok([format_input(r["question"], r["answer"], r["context"]) for r in batch],
                           max_length=self.cfg.data.max_src_len, truncation=True, padding=True,
                           return_tensors="pt").to(self.env.device)
            try:
                seqs = model.generate(**enc, max_new_tokens=g.max_new_tokens, **self._kwargs(g.decoding))
            except (ValueError, TypeError, NotImplementedError) as exc:
                logger.warning(f"{g.decoding} không chạy được ({exc}); chuyển sang sampling")
                g.decoding = "sampling"
                seqs = model.generate(**enc, max_new_tokens=g.max_new_tokens, **self._kwargs("sampling"))
            texts = self.tok.batch_decode(seqs, skip_special_tokens=True)
            for j, r in enumerate(batch):
                seen, cands = {" ".join(syllables(r["answer"]))}, []
                for t in texts[j * n:(j + 1) * n]:
                    k = " ".join(syllables(t))
                    if k and k not in seen:
                        seen.add(k)
                        cands.append(t.strip())
                out.append(cands)
        return out

    def score(self, rows: list[dict], cands: list[list[str]]) -> dict:
        hyps, refs, rl, rl_best, divs = [], [], [], [], []
        copy_top1 = copy_all = n_all = 0
        for r, cs in zip(rows, cands):
            ref = [syllables(d) for d in r["distractors"]]
            top = syllables(cs[0]) if cs else []
            hyps.append(top)
            refs.append(ref)
            rl.append(max((rouge_l(top, x) for x in ref), default=0.0))
            rl_best.append(max((rouge_l(syllables(c), x) for c in cs for x in ref), default=0.0))
            copy_top1 += bool(cs) and key_recall(cs[0], r["answer"]) >= 0.95
            copy_all += sum(key_recall(c, r["answer"]) >= 0.95 for c in cs)
            n_all += len(cs)
            sets = [set(syllables(c)) for c in cs]
            jac = [len(a & b) / len(a | b) for a, b in combinations(sets, 2) if a | b]
            if jac:
                divs.append(1 - sum(jac) / len(jac))
        ref_copy = [key_recall(d, r["answer"]) >= 0.95 for r in rows for d in r["distractors"]]
        n = max(len(rows), 1)
        return {"n_questions": len(rows), **corpus_bleu(hyps, refs), "rouge_l": round(100 * sum(rl) / n, 2),
                "rouge_l_best_of_n": round(100 * sum(rl_best) / n, 2), "copy_rate_top1": round(copy_top1 / n, 4),
                "copy_rate_all": round(copy_all / max(n_all, 1), 4),
                "ref_copy_rate": round(sum(ref_copy) / max(len(ref_copy), 1), 4),
                "diversity": round(sum(divs) / len(divs), 4) if divs else 0.0, "n_candidates": round(n_all / n, 2)}

    def evaluate(self, model, limit: int | None = None, sample_path: Path | None = None) -> dict:
        rows = self.rows[:limit] if limit else self.rows
        if not rows:
            return {}
        cands = self.generate(model, rows)
        if sample_path is not None:
            with sample_path.open("w", encoding="utf-8") as f:
                for r, c in zip(rows, cands):
                    f.write(json.dumps({"question": r["question"], "answer": r["answer"],
                                        "references": r["distractors"], "candidates": c}, ensure_ascii=False) + "\n")
        return self.score(rows, cands)


# %% [11] Loaders
def get_loader(dataset: Dataset, cfg: AppConfig, env: RuntimeEnv, collate, train: bool) -> DataLoader:
    """DistributedSampler đệm thêm mẫu ở dev để chia đều cho các GPU: loss dev lệch rất nhẹ. Số liệu báo cáo cuối
    lấy từ GenerationEvaluator (chạy một process, không đệm)."""
    sampler = DistributedSampler(dataset, shuffle=train, drop_last=train) if env.is_distributed else None
    return DataLoader(dataset, batch_size=cfg.training.batch_size, sampler=sampler,
                      shuffle=(train and sampler is None), drop_last=False, collate_fn=collate,
                      num_workers=cfg.data.num_workers, pin_memory=env.device.type == "cuda")


def data_ingestion(cfg: AppConfig, env: RuntimeEnv, tokenizer, paths: RunPaths):
    if env.is_main_process:
        DataProcessor(cfg, tokenizer, paths).process()
    if env.is_distributed:
        dist.barrier()
    train_ds = DistractorDataset(paths.cache_dir / "train.pt")
    dev_ds = DistractorDataset(paths.cache_dir / "dev.pt")
    collate = Collator(tokenizer.pad_token_id)
    return get_loader(train_ds, cfg, env, collate, True), get_loader(dev_ds, cfg, env, collate, False)


# %% [12] Plotting
def plot_history(history: list[dict], paths: RunPaths) -> None:
    if not history:
        return
    plt.rcParams.update({"font.family": "serif", "figure.dpi": 300})
    epochs = [h["epoch"] + 1 for h in history]
    panels = [("total_loss", "Loss (CE + λ·UL)"), ("ul", "Unlikelihood")]
    has_gen = any("val_gen_rouge_l" in h for h in history)
    if has_gen:
        panels += [("gen_rouge_l", "ROUGE-L (dev, sinh)"), ("gen_copy_rate_all", "Tỉ lệ chép đáp án (dev)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 3.2))
    for ax, (key, title) in zip(axes, panels):
        if f"train_{key}" in history[0]:
            ax.plot(epochs, [h[f"train_{key}"] for h in history], "b-", marker="o", label="train")
        ax.plot(epochs, [h.get(f"val_{key}", float("nan")) for h in history], "r--", marker="s", label="val")
        ax.set_title(title)
        ax.set_xlabel("epoch")
        ax.xaxis.get_major_locator().set_params(integer=True)
        ax.grid(alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(paths.run_dir / "training_curves.pdf")
    plt.close(fig)


# %% [13] main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="*", default=[], metavar="SECTION.KEY=VALUE")
    args = ap.parse_args()
    cfg = AppConfig()
    cfg.apply_overrides(args.set)

    ddp_setup()
    env = RuntimeEnv(cfg.training.precision)
    torch.manual_seed(cfg.training.seed)

    name = [cfg.logging.fixed_run_dir or generate_run_name(cfg) if env.is_main_process else None]
    if env.is_distributed:
        dist.broadcast_object_list(name, src=0)   # mọi rank cùng một thư mục
    paths = RunPaths.from_cfg(cfg, name[0])
    if env.is_main_process:
        paths.mkdirs()
    if env.is_distributed:
        dist.barrier()
    setup_ddp_loguru(env, paths)

    try:
        logger.info("+" * 20 + " CONFIG " + "+" * 20)
        logger.info(f"Run: {paths.run_dir} | world_size={env.world_size} | device={env.device} | "
                    f"amp={env.amp_enabled} ({env.amp_dtype}) | λ={cfg.training.lam}")
        if env.is_main_process:
            (paths.run_dir / "config.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
                                                       encoding="utf-8")

        logger.info("+" * 20 + " PREPROCESSING DATA " + "+" * 20)
        tokenizer = AutoTokenizer.from_pretrained(cfg.model.model_name)
        train_loader, val_loader = data_ingestion(cfg, env, tokenizer, paths)

        logger.info("+" * 20 + " BUILDING MODEL " + "+" * 20)
        model = build_model(cfg)
        loss_fn = UnlikelihoodLoss(cfg.training.lam)
        callbacks = CallbackList([ModelCheckpoint(), EarlyStopping(cfg), CSVLogger(paths)], env)
        gen_eval = GenerationEvaluator(cfg, env, tokenizer, Path(cfg.data.data_dir) / cfg.data.dev_q_file) \
            if cfg.data.gen_eval_limit > 0 else None
        trainer = DistractorGenTrainer(cfg, env, model, loss_fn, train_loader, val_loader, paths, callbacks,
                                       LossEvaluator(env), gen_eval, tokenizer)

        logger.info("+" * 20 + " TRAINING " + "+" * 20)
        state = trainer.fit()

        if env.is_main_process:
            logger.info("+" * 20 + " TESTING (best_model) " + "+" * 20)
            best = AutoModelForSeq2SeqLM.from_pretrained(paths.best_model_dir).to(env.device)
            results = {}
            for f in cfg.data.test_q_files:
                ev = GenerationEvaluator(cfg, env, tokenizer, Path(cfg.data.data_dir) / f)
                results[Path(f).stem] = ev.evaluate(best, sample_path=paths.run_dir / f"samples_{Path(f).stem}.jsonl")
                logger.info(f"{Path(f).stem}: {json.dumps(results[Path(f).stem], ensure_ascii=False)}")
            if gen_eval is not None:
                results["dev"] = gen_eval.evaluate(best, limit=cfg.data.gen_eval_limit)
            (paths.run_dir / "final_metrics.json").write_text(json.dumps(
                {"lam": cfg.training.lam, "best_epoch": state.best_epoch, "best_metric": state.best_metric,
                 **results}, ensure_ascii=False, indent=2), encoding="utf-8")
            plot_history(state.history, paths)
            logger.info(f"Xong. Model tốt nhất: {paths.best_model_dir}")
        if env.is_distributed:
            dist.barrier()
    except Exception as e:
        logger.error(f"[Rank {env.global_rank}] Training Error: {e}")
        raise
    finally:
        if env.is_distributed and dist.is_initialized():
            dist.destroy_process_group()


if __name__ == "__main__":
    main()
