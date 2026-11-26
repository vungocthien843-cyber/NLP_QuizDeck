"""Kiểm thử script huấn luyện training/kaggle/train_ddp.py: loss (K1), chỉ số (K5), chạy thử trọn vòng một tiến
trình với T5 tí hon và tokenizer tự tạo (không cần mạng, ~20 giây trên CPU)."""
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
spm = pytest.importorskip("sentencepiece")
pytest.importorskip("loguru")
pytest.importorskip("torchmetrics")

SCRIPT = Path(__file__).resolve().parents[1] / "kaggle" / "train_ddp.py"
spec = importlib.util.spec_from_file_location("train_ddp", SCRIPT)
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


def _batch(seed=0, B=2, Tn=5, V=11):
    g = torch.Generator().manual_seed(seed)
    logits = torch.randn(B, Tn, V, generator=g, requires_grad=True)
    labels = torch.randint(0, V, (B, Tn), generator=g)
    labels[1, 3:] = -100
    neg = torch.tensor([[2, 5, -1], [7, -1, -1]])
    return logits, labels, neg


# ---------- Loss (K1) ----------
def test_loss_lambda_zero_is_cross_entropy():
    logits, labels, neg = _batch()
    loss, d = T.UnlikelihoodLoss(0.0)(logits, {"labels": labels, "neg_ids": neg})
    ref = torch.nn.functional.cross_entropy(logits.transpose(1, 2), labels, ignore_index=-100)
    assert torch.allclose(loss, ref) and d["ul"] == 0.0 and d["valid_count"] == 8


def test_unlikelihood_matches_manual_formula():
    logits, labels, neg = _batch()
    _, d = T.UnlikelihoodLoss(1.0)(logits, {"labels": labels, "neg_ids": neg})
    p = logits.softmax(-1)
    terms = [-sum(torch.log(1 - p[b, t, i]) for i in neg[b].tolist() if i >= 0)
             for b in range(2) for t in range(5) if labels[b, t] != -100]
    assert d["ul"] == pytest.approx(float(torch.stack(terms).mean()), abs=1e-5)


def test_unlikelihood_gradient_lowers_penalised_token():
    logits, labels, neg = _batch()
    full, _ = T.UnlikelihoodLoss(1.0)(logits, {"labels": labels, "neg_ids": neg})
    ce, _ = T.UnlikelihoodLoss(0.0)(logits, {"labels": labels, "neg_ids": neg})
    (g_full,), (g_ce,) = torch.autograd.grad(full, logits), torch.autograd.grad(ce, logits)
    assert (g_full - g_ce)[0, 0, 2] > 0
    assert torch.allclose((g_full - g_ce)[1, 4], torch.zeros(11), atol=1e-7)   # vị trí -100 không bị ảnh hưởng


# ---------- Chỉ số (K5), callback ----------
def test_metrics_and_overrides():
    assert T.corpus_bleu([["a", "b", "c", "d"]], [[["a", "b", "c", "d"]]])["bleu_4"] == 100.0
    assert T.rouge_l(["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    assert T.key_recall("TF–IDF (Term Frequency–Inverse Document Frequency)", "TF-IDF") == 1.0
    cfg = T.AppConfig()
    cfg.apply_overrides(["training.lam=0.5", 'data.test_q_files=["a.jsonl"]', "logging.run_name=x"])
    assert cfg.training.lam == 0.5 and cfg.data.test_q_files == ("a.jsonl",) and cfg.logging.run_name == "x"
    with pytest.raises(KeyError):
        cfg.apply_overrides(["training.not_a_field=1"])


def test_early_stopping_respects_warmup_and_patience():
    cfg = T.AppConfig()
    cfg.training.num_train_epochs, cfg.callbacks.warmup_epochs, cfg.callbacks.early_stopping_patience = 6, 1, 2
    es, state = T.EarlyStopping(cfg), T.TrainerState()
    stops = []
    for epoch, loss in enumerate([5.0, 5.1, 5.2, 5.3]):
        state.epoch, control = epoch, T.TrainerControl()
        es.on_epoch_end(cfg, state, control, {"val_total_loss": loss})
        stops.append(control.should_training_stop)
    assert stops == [False, False, True, True]


# ---------- Chạy thử trọn vòng ----------
WORDS = ("mô hình ngôn ngữ vector từ câu văn bản trọng số tần suất hiếm nhiều kho tài liệu học máy mạng nơ ron "
         "chú ý biểu diễn nhúng tfidf bm25 word2vec onehot bagofwords lstm").split()


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    d = tmp_path_factory.mktemp("tiny")
    rng = random.Random(0)
    (d / "c.txt").write_text("\n".join(" ".join(rng.choices(WORDS, k=12)) for _ in range(2000))
                             + "\ncâu hỏi: | đáp án: | ngữ cảnh: ?", encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(d / "c.txt"), model_prefix=str(d / "sp"), vocab_size=100,
                                   character_coverage=1.0, pad_id=0, eos_id=1, unk_id=2, bos_id=-1,
                                   user_defined_symbols=["|", ":", "?"])
    tok = transformers.T5Tokenizer(vocab_file=str(d / "sp.model"), extra_ids=0, legacy=False)
    cfg = transformers.T5Config(vocab_size=len(tok), d_model=32, d_ff=64, num_layers=1, num_decoder_layers=1,
                                num_heads=2, d_kv=16, decoder_start_token_id=0, pad_token_id=0, eos_token_id=1)
    transformers.T5ForConditionalGeneration(cfg).save_pretrained(d / "model")
    tok.save_pretrained(d / "model")

    from training import prepare_data
    raw = d / "raw"
    raw.mkdir()
    rows = [{"context": " ".join(rng.choices(WORDS, k=30)), "question": "mô hình nào biểu diễn văn bản ?",
             "choices": rng.sample(["tfidf", "bm25", "word2vec", "onehot", "bagofwords", "lstm"], 4),
             "correctchoice": 0} for _ in range(60)]
    for name, part in (("train", rows[:40]), ("val", rows[40:50]), ("test", rows[50:])):
        (raw / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in part), encoding="utf-8")
    prepare_data.main(["--vsmrc", str(raw), "--out", str(d / "proc")])
    return d


def test_end_to_end_single_process(tiny):
    runs = tiny / "runs"
    cmd = [sys.executable, str(SCRIPT), "--set", f'data.data_dir="{tiny / "proc"}"', f'model.model_name="{tiny / "model"}"',
           f'logging.artifact_path="{runs}"', 'logging.fixed_run_dir="t"', "training.num_train_epochs=2",
           "training.batch_size=4", "data.num_workers=0", "data.gen_eval_limit=4", "generation.n_candidates=4",
           "data.max_src_len=64", "data.max_tgt_len=8", "generation.max_new_tokens=8", "training.precision=fp32"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    run = runs / "t"
    for p in ("best_model/config.json", "best_model/model.safetensors", "best_model/trainer_state.json",
              "last_checkpoint.pt", "logs/training_logs.csv", "logs/run_rank_0.log", "final_metrics.json",
              "training_curves.pdf", "config.json"):
        assert (run / p).exists(), p
    m = json.loads((run / "final_metrics.json").read_text(encoding="utf-8"))
    assert {"test_vsmrc_q", "dev", "lam", "best_epoch"} <= set(m)
    assert {"bleu_1", "rouge_l", "copy_rate_all", "ref_copy_rate", "diversity"} <= set(m["test_vsmrc_q"])
    header = (run / "logs/training_logs.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header[:5] == ["epoch", "global_step", "train_total_loss", "train_ce", "train_ul"]
    assert "val_gen_copy_rate_all" in header
