"""Kiểm thử pipeline v2 không cần DB, GPU hay API: LLM, ViT5, NLI và reranker đều được giả lập.
Chạy: python -m pytest -q tests/"""
import asyncio
import json
import os
import random
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/x")

from app.config import get_config  # noqa: E402
from app.generation import candidates, filters, pipeline_v2, selector  # noqa: E402
from app.llm_client import LLMResult  # noqa: E402
from app.models import Chunk  # noqa: E402

# Ví dụ trong tài liệu "Bài 2 – Chung et al. 2020", mục 5.1
SCORES = {"TF-IDF": 3.0, "BM25": 2.9, "Bag-of-Words": 1.2, "Đếm số lần từ xuất hiện trong văn bản": 1.4,
          "One-hot encoding": 0.3, "Word2Vec": 0.2, "Tần suất từ (TF)": 1.4}


# ---------- selector (K4) ----------
def test_select_reproduces_worked_example():
    cands = ["BM25", "Bag-of-Words", "Đếm số lần từ xuất hiện trong văn bản", "One-hot encoding", "Word2Vec"]
    chosen, info = selector.select(SCORES["TF-IDF"], [SCORES[c] for c in cands], "entropy", 0.15)
    assert {cands[i] for i in chosen} == {"Bag-of-Words", "Đếm số lần từ xuất hiện trong văn bản", "One-hot encoding"}
    assert info["entropy"] == pytest.approx(1.327, abs=1e-3)
    assert info["n_sets"] == 10 and info["n_sets_ok"] == 4
    # bỏ ràng buộc δ (đúng như bài gốc) → chọn bộ có BM25, câu có hai đáp án đúng
    chosen2, info2 = selector.select(SCORES["TF-IDF"], [SCORES[c] for c in cands], "entropy_no_delta", 0.15)
    assert "BM25" in {cands[i] for i in chosen2}
    assert info2["entropy"] == pytest.approx(1.635, abs=1e-3)


def test_select_other_modes_and_edge_cases():
    assert selector.select(1.0, [0.1, 0.2], "entropy")[0] is None
    assert selector.select(1.0, [0.1, 0.2, 0.3, 0.4], "top3")[0] == (0, 1, 2)
    assert len(selector.select(1.0, [0.1] * 5, "random", rng=random.Random(0))[0]) == 3
    none, info = selector.select(0.0, [5.0, 5.0, 5.0], "entropy", 0.15)       # đáp án đúng không thắng
    assert none is None and info["reason"] == "no_set_satisfies_delta"


def test_select_diversity_constraint(monkeypatch):
    """Kế hoạch v3, B4: bộ entropy cao nhất có 3 phương án cùng loại lỗi → chọn bộ khác phủ ≥ 2 loại;
    phương án khong_ro bị trừ điểm; không bộ nào đa dạng được thì nới về mức cũ."""
    cfg = get_config().distractor
    monkeypatch.setattr(cfg, "min_error_types", 2)
    monkeypatch.setattr(cfg, "unclear_penalty", 0.3)
    scores = [1.0, 1.0, 1.0, 0.2, 0.1]
    same = ["dao_nhan_qua"] * 3
    types = same + ["sai_mot_chi_tiet", "khong_ro"]
    chosen0, _ = selector.select(3.0, scores, "entropy", 0.15)
    assert chosen0 == (0, 1, 2)                                   # không có error_types: như v2
    chosen, info = selector.select(3.0, scores, "entropy", 0.15, error_types=types)
    assert 3 in chosen and 4 not in chosen                        # thêm loại khác, tránh khong_ro
    assert info["form_level"] == "diverse" and info["n_error_types"] == 2
    chosen2, info2 = selector.select(3.0, scores[:3] + [0.1], "entropy", 0.15, error_types=same + ["khong_ro"])
    assert info2["form_level"] == "none" and chosen2 == (0, 1, 2)  # không đa dạng được: nới, vẫn tránh khong_ro
    monkeypatch.setattr(cfg, "min_error_types", 0)
    chosen3, _ = selector.select(3.0, scores, "entropy", 0.15, error_types=types)
    assert chosen3 == (0, 1, 2)                                   # tắt ràng buộc
    assert selector.diverse_ok(["a", "a", None], 2) is False and selector.diverse_ok(["a", "b", "khong_ro"], 2)


def test_shuffle_keeps_origin_and_v1_option_meta():
    from app.generation.common import build_option_meta, shuffle_options
    from app.schemas import GeneratedMCQ
    mcq = GeneratedMCQ.model_validate({
        "key_point": "k", "evidence": "e", "stem": "S?", "explanation": "x", "bloom_level": "remember",
        "source_chunk_ids": [1],
        "options": [{"text": t, "is_correct": i == 0, "rationale": "r"} for i, t in enumerate("WXYZ")]})
    for seed in range(5):
        sh = shuffle_options(mcq, random.Random(seed))
        assert all(sh.options[l] == mcq.options[i].text for l, i in sh.origin.items())
        meta = build_option_meta(mcq, sh, None)
        assert meta[sh.answer] == {"role": "key"}
        assert all(m["source"] == "v1" and m["error_type"] is None for l, m in meta.items() if l != sh.answer)


def test_neighbor_text_cleanup_and_admin_filter():
    """v3: bỏ cụm lặp do trích slide; slide lộ trình / chuẩn đầu ra không được dùng làm khái niệm lân cận."""
    assert pipeline_v2.clean_slide_text("Đo mô hình cho cho đúng đúng") == "Đo mô hình cho đúng"
    assert pipeline_v2.clean_slide_text("MLE = đếm chia đếm đếm chia đếm") == "MLE = đếm chia đếm"
    assert pipeline_v2.is_admin_slide("Lộ trình: CHƯƠNG 4 · 7 TIẾT")
    assert pipeline_v2.is_admin_slide("Sau chương này: CHUẨN ĐẦU RA · CLO2")
    assert not pipeline_v2.is_admin_slide("Bigram add-k: chọn k nhỏ")


# ---------- filters (K5) ----------
def test_rule_filters():
    cs = [candidates.Candidate(t, "vit5") for t in [
        "TF–IDF (Term Frequency–Inverse Document Frequency)", "Tất cả đều đúng", "BM25",
        "Một phương án rất rất dài dòng vượt xa độ dài của đáp án đúng rất nhiều lần luôn đó"]]
    filters.apply_rule_filters(cs, "TF-IDF")
    assert [c.rejected_at for c in cs] == ["copy", "form", None, "form"]
    assert cs[0].copy_score == 1.0


# ---------- pipeline đầy đủ với giả lập ----------
CONTEXT_TEXT = ("TF-IDF gán trọng số cao cho từ xuất hiện nhiều trong một văn bản nhưng hiếm trong toàn bộ kho "
                "văn bản. Bag-of-Words biểu diễn văn bản bằng số lần xuất hiện của từng từ.")
EVIDENCE = "TF-IDF gán trọng số cao cho từ xuất hiện nhiều trong một văn bản nhưng hiếm trong toàn bộ kho văn bản."
STEM = "Kỹ thuật biểu diễn văn bản nào ưu tiên từ xuất hiện nhiều trong một văn bản nhưng hiếm trong kho?"


def _llm_reply(name: str) -> dict:
    if name == "mcq_key":
        return {"key_point": "TF-IDF ưu tiên từ đặc trưng", "evidence": EVIDENCE, "answer": "TF-IDF",
                "answer_type": "thuat_ngu", "source_chunk_ids": [1]}
    if name == "mcq_stem":
        return {"stem": STEM}
    if name == "mcq_misconception":
        return {"candidates": [{"text": "Dùng riêng IDF", "error_type": "sai_mot_chi_tiet"},
                               {"text": "Tần suất từ (TF)", "error_type": "khai_quat_qua_muc"},
                               {"text": "Đếm số lần mỗi từ xuất hiện trong toàn bộ văn bản đầu vào", "error_type": "x"}]}
    if name == "mcq_tag_error":      # gắn nhãn theo thứ tự, xoay vòng các loại; phương án thứ 4 là "khong_ro"
        types = ["nham_khai_niem_lan_can", "gan_nham_thuoc_tinh", "khai_quat_qua_muc", "khong_ro", "dao_nhan_qua"]
        return {"labels": [{"i": i, "error_type": types[i % len(types)]} for i in range(12)]}
    if name == "mcq_explain":
        return {"rationales": ["Đúng: TF kết hợp IDF.", "BoW chỉ đếm tần suất.", "Chỉ là phần TF.", "One-hot không có trọng số."],
                "explanation": "TF-IDF = TF × IDF."}
    raise AssertionError(name)


@pytest.fixture
def stubs(monkeypatch):
    calls = []

    async def fake_acomplete(role, messages, **kw):
        text = messages[-1]["content"]
        name = ("mcq_key" if "bước 1/4" in text else "mcq_stem" if "bước 2/4" in text else
                "mcq_explain" if "bước cuối" in text else
                "mcq_tag_error" if "GẮN NHÃN HIỂU NHẦM" in text else "mcq_misconception")
        calls.append(name)
        return LLMResult(json.dumps(_llm_reply(name), ensure_ascii=False), "fake", 10, 5, 0.0)

    class FakeGen:
        def generate(self, q, a, c, n, decoding):
            return ["BM25", "Bag-of-Words", "TF–IDF (Term Frequency–Inverse Document Frequency)", "One-hot encoding",
                    "Word2Vec", "BM25", "TF-IDF"]

    class FakeNLI:
        def entailment(self, premise, hyps):
            return [0.9 if ("Dùng riêng IDF" in h or h.endswith("TF-IDF")) else 0.05 for h in hyps]

    class FakeReranker:
        def scores(self, query, texts, normalize=False):
            return [SCORES.get(t, 0.0) for t in texts]

    import app.local_models as lm
    import app.retrieval.reranker as rr
    monkeypatch.setattr(pipeline_v2, "acomplete", fake_acomplete)
    monkeypatch.setattr(candidates, "acomplete", fake_acomplete)
    monkeypatch.setattr(lm, "vit5_available", lambda: True)
    monkeypatch.setattr(lm, "get_generator", lambda: FakeGen())
    monkeypatch.setattr(lm, "get_nli", lambda: FakeNLI())
    monkeypatch.setattr(rr, "get_reranker", lambda: FakeReranker())
    cfg = get_config().distractor
    monkeypatch.setattr(cfg, "sources", ["vit5", "llm"])
    monkeypatch.setattr(cfg, "scorer", "reranker")
    monkeypatch.setattr(cfg, "selection", "entropy")
    monkeypatch.setattr(cfg, "delta", 0.15)
    monkeypatch.setattr(cfg, "min_alive", 0)
    monkeypatch.setattr(cfg, "llm_candidates", 3)
    monkeypatch.setattr(pipeline_v2, "neighbor_concepts", lambda seed, ctx, kp, n: ["BM25: hàm xếp hạng cải tiến TF-IDF"])
    return calls


def _seed():
    chunk = Chunk(id=1, document_id=1, slide_no=3, slide_end=None, raw_text=CONTEXT_TEXT, notes=None,
                  vlm_caption=None, embed_text=f"[Slide 3]\n{CONTEXT_TEXT}")
    return SimpleNamespace(chunk=chunk, bloom_level="remember"), [chunk]


def test_pipeline_v2_end_to_end(stubs):
    seed, context = _seed()
    mcq, report = asyncio.run(pipeline_v2.generate(seed, context, ["Câu cũ?"]))
    texts = [o.text for o in mcq.options]
    assert texts[0] == "TF-IDF" and mcq.options[0].is_correct
    assert set(texts[1:]) == {"Bag-of-Words", "Tần suất từ (TF)", "One-hot encoding"}
    assert all(o.rationale for o in mcq.options)
    pool = {c["text"]: c for c in report["candidates"]}
    assert pool["TF–IDF (Term Frequency–Inverse Document Frequency)"]["rejected_at"] == "copy"
    assert pool["Dùng riêng IDF"]["rejected_at"] == "nli"
    assert pool["BM25"]["rejected_at"] is None and not pool["BM25"]["selected"]      # loại nhờ δ, không nhờ NLI
    assert pool["Đếm số lần mỗi từ xuất hiện trong toàn bộ văn bản đầu vào"]["rejected_at"] == "form"  # lệch độ dài
    assert sum(c["selected"] for c in report["candidates"]) == 3
    assert {c["source"] for c in report["candidates"]} == {"vit5", "llm"}
    sel = report["selection"]
    assert sel["entropy"] == pytest.approx(1.327, abs=1e-3) and sel["margin"] >= 0.15
    assert report["answer_type"] == "thuat_ngu"
    assert "diverse" in sel["form_level"] and sel["n_error_types"] >= 2
    assert stubs == ["mcq_key", "mcq_stem", "mcq_misconception", "mcq_tag_error", "mcq_explain"]
    assert [c["step"] for c in report["llm_calls"]] == stubs


def test_pipeline_v2_rejects_bad_evidence(stubs, monkeypatch):
    seed, context = _seed()
    orig = _llm_reply

    def bad(name):
        r = orig(name)
        if name == "mcq_key":
            r["evidence"] = "Một câu hoàn toàn không có trong slide bài giảng này."
        return r
    monkeypatch.setattr(__import__(__name__), "_llm_reply", bad, raising=False)
    globals()["_llm_reply"] = bad
    try:
        with pytest.raises(pipeline_v2.StepFailed) as e:
            asyncio.run(pipeline_v2.generate(seed, context, []))
        assert e.value.step == "key"
    finally:
        globals()["_llm_reply"] = orig


def test_pipeline_v2_without_vit5_uses_llm_only(stubs, monkeypatch):
    import app.local_models as lm
    monkeypatch.setattr(lm, "vit5_available", lambda: False)
    monkeypatch.setattr(get_config().distractor, "selection", "top3")
    seed, context = _seed()
    # chỉ còn 1 ứng viên LLM sống (cái kia bị NLI loại) → sinh bù vẫn thiếu → StepFailed ở bước chọn
    with pytest.raises(pipeline_v2.StepFailed) as e:
        asyncio.run(pipeline_v2.generate(seed, context, []))
    assert e.value.step == "selection"
    assert {c["source"] for c in e.value.details["pool"]} == {"llm"}


def test_pipeline_v2_reports_timing_and_vit5_status(stubs, monkeypatch):
    """Kế hoạch v3, A1 + A5: report ghi thời gian từng bước và trạng thái nguồn vit5 của từng câu."""
    seed, context = _seed()
    _, report = asyncio.run(pipeline_v2.generate(seed, context, []))
    assert set(report["timing"]) == {"key", "stem", "distractors", "explain"}
    assert {"vit5", "llm", "nli", "tag", "score"} <= set(report["selection"]["timing_detail"])
    assert report["selection"]["vit5"][0]["status"] == "ok"

    import app.local_models as lm
    monkeypatch.setattr(lm, "vit5_available", lambda: False)
    with pytest.raises(pipeline_v2.StepFailed) as e:
        asyncio.run(pipeline_v2.generate(seed, context, []))
    assert e.value.details["vit5"][0]["status"] == "unavailable"
    assert "distractors" in e.value.details["timing"]


def test_tagging_labels_every_alive_candidate(stubs):
    """Kế hoạch v3, B2: mọi ứng viên còn sống (cả vit5) có nhãn; ứng viên llm giữ nhãn tự khai; bị loại thì không gắn."""
    from app.prompts import misconception_types
    seed, context = _seed()
    _, report = asyncio.run(pipeline_v2.generate(seed, context, []))
    valid = set(misconception_types()) | {"khong_ro"}
    alive = [c for c in report["candidates"] if c["rejected_at"] is None]
    assert alive and all(c["error_type"] in valid for c in alive)
    assert any(c["source"] == "vit5" and c["error_type"] for c in alive)
    tf = next(c for c in report["candidates"] if c["text"] == "Tần suất từ (TF)")
    assert tf["error_type_self"] == "khai_quat_qua_muc"
    bad = next(c for c in report["candidates"] if c["text"].startswith("Đếm số lần"))
    assert bad["error_type_self"] is None                 # mã "x" không hợp lệ bị bỏ
    assert report["selection"]["tagging"][0]["tagged"] == len(alive)


def test_tagging_off_and_tagging_failure(stubs, monkeypatch):
    monkeypatch.setattr(get_config().distractor, "tag_errors", False)
    seed, context = _seed()
    asyncio.run(pipeline_v2.generate(seed, context, []))
    assert "mcq_tag_error" not in stubs
    # bật lại nhưng gọi LLM lỗi: câu hỏi vẫn sinh được, nhãn tự khai giữ nguyên
    monkeypatch.setattr(get_config().distractor, "tag_errors", True)
    orig = candidates.acomplete

    async def failing(role, messages, **kw):
        if "GẮN NHÃN HIỂU NHẦM" in messages[-1]["content"]:
            raise RuntimeError("API lỗi")
        return await orig(role, messages, **kw)
    monkeypatch.setattr(candidates, "acomplete", failing)
    mcq, report = asyncio.run(pipeline_v2.generate(seed, context, []))
    assert "error" in report["selection"]["tagging"][0]
    tf = next(c for c in report["candidates"] if c["text"] == "Tần suất từ (TF)")
    assert tf["error_type"] == "khai_quat_qua_muc"


def test_neighbors_reach_prompt_and_min_alive_refills(stubs, monkeypatch):
    """v3 B3: khái niệm lân cận vào prompt hiểu nhầm; A3: còn < min_alive ứng viên thì sinh bù trước khi chọn."""
    seen = []
    orig = candidates.acomplete

    async def spy(role, messages, **kw):
        seen.append(messages[-1]["content"])
        return await orig(role, messages, **kw)
    monkeypatch.setattr(candidates, "acomplete", spy)
    seed, context = _seed()
    _, report = asyncio.run(pipeline_v2.generate(seed, context, []))
    assert any("BM25: hàm xếp hạng cải tiến TF-IDF" in t and "KHÁI NIỆM LÂN CẬN" in t for t in seen)
    assert report["selection"]["round"] == 0
    monkeypatch.setattr(get_config().distractor, "min_alive", 99)
    _, report2 = asyncio.run(pipeline_v2.generate(seed, context, []))
    assert report2["selection"]["round"] == get_config().distractor.refill_rounds   # đã sinh bù


# ---------- nối vào bank_builder: hậu kiểm, chống trùng, lưu ứng viên ----------
def test_bank_builder_saves_v2_question(stubs, monkeypatch):
    from app.generation import bank_builder as bb
    from app.generation.validator import ValidationResult
    from app.models import DistractorCandidate, Question

    saved = []

    class FakeDB:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def add(self, obj): saved.append(obj)
        def add_all(self, objs): saved.extend(objs)
        def flush(self):
            for o in saved:
                if isinstance(o, Question):
                    o.id = 99
        def commit(self): pass

    seed, context = _seed()
    monkeypatch.setattr(get_config().bank, "pipeline", "v2")
    monkeypatch.setattr(bb, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(bb, "_load_context", lambda s: context)
    monkeypatch.setattr(bb, "_embed_for_dedup", lambda m: None)
    monkeypatch.setattr(bb, "check_duplicate", lambda db, e, th: ValidationResult(True))
    state = bb.BankState(document_id=1, session_no=None, target=1, existing_stems=[])
    asyncio.run(bb.process_seed(seed, asyncio.Semaphore(1), state))

    assert state.accepted == 1
    q = next(o for o in saved if isinstance(o, Question))
    assert q.pipeline_version == "v2" and q.status == "accepted" and q.answer_type == "thuat_ngu"
    assert q.selection["entropy"] == pytest.approx(1.327, abs=1e-3)
    assert q.validation["pipeline_version"] == "v2" and q.validation["llm_calls"]
    assert set(q.options.values()) == {"TF-IDF", "Bag-of-Words", "Tần suất từ (TF)", "One-hot encoding"}
    assert q.options[q.answer] == "TF-IDF"
    cands = [o for o in saved if isinstance(o, DistractorCandidate)]
    assert cands and all(c.question_id == 99 for c in cands)
    assert sum(c.selected for c in cands) == 3
    # v3 (B5): option_meta khớp đúng chữ cái sau khi xáo, mang loại hiểu nhầm của ứng viên được chọn
    meta = q.option_meta
    assert set(meta) == set("ABCD") and meta[q.answer] == {"role": "key"}
    by_text = {c.text: c for c in cands}
    for letter, m in meta.items():
        if letter != q.answer:
            c = by_text[q.options[letter]]
            assert m["role"] == "distractor" and c.selected
            assert m["source"] == c.source and m["error_type"] == c.error_type
    assert q.concept == "TF-IDF ưu tiên từ đặc trưng"


# ---------- eval/v2: đổi cấu hình tạm thời, chọn lại bộ 3 trên cùng ứng viên, model giải ----------
def test_ablation_helpers(stubs, monkeypatch):
    from eval.v2 import run_ablation as ra

    cfg = get_config()
    before = (cfg.bank.pipeline, list(cfg.distractor.sources))
    with ra.override(ra.CONFIGS["C1"]):
        assert cfg.distractor.sources == ["llm"] and cfg.bank.pipeline == "v2"
    assert (cfg.bank.pipeline, list(cfg.distractor.sources)) == before

    seed, context = _seed()
    q, meta = asyncio.run(ra.generate(seed, context))
    assert meta["passed"] and q["answer"] == "TF-IDF" and len(q["distractors"]) == 3
    alts = ra.alt_selections(q, meta)
    assert set(alts) == set(ra.SELECTION_MODES)
    assert "BM25" in alts["entropy_no_delta"]["distractors"] and "BM25" not in alts["entropy"]["distractors"]

    async def fake_solver(role, messages, **kw):
        text = messages[-1]["content"]
        letter = next(line[0] for line in text.splitlines() if line.endswith(". TF-IDF"))
        return LLMResult(json.dumps({"choice": letter}), "fake", 1, 1, 0.0)
    monkeypatch.setattr(ra, "acomplete", fake_solver)
    m = asyncio.run(ra.solver_metrics([q], runs=2, seed=1))
    assert m["open_book_correct"] == 1.0 and m["options_only_correct"] == 1.0
    assert ra.copy_rate([q]) == 0.0


def test_difficulty_percentile_handles_ties():
    """v3 D4: nhiều câu trùng điểm (câu v1 không có margin) không được dồn hết vào một mức."""
    from app.learner.difficulty import _percentile
    p = _percentile({1: 0.5, 2: 0.5, 3: 0.5, 4: 0.9, 5: 0.1})
    assert p[5] == 0.0 and p[4] == 1.0 and p[1] == p[2] == p[3] == 0.5


def test_ablation_resume_after_interrupt(tmp_path, monkeypatch):
    """Mốc 3: lần chạy dài bị ngắt (máy ngủ, Docker tắt) thì chạy lại chỉ sinh nốt các hạt giống còn thiếu."""
    from types import SimpleNamespace

    from eval.v2 import run_ablation as ra
    seeds = [SimpleNamespace(chunk=SimpleNamespace(id=i)) for i in range(6)]
    calls = []

    async def gen(s, ctx, stop_after=None):
        calls.append(s.chunk.id)
        if stop_after is not None and len(calls) > stop_after:
            raise KeyboardInterrupt
        return {"stem": f"q{s.chunk.id}"}, {"seed_chunk": s.chunk.id, "passed": True}

    monkeypatch.setattr(ra, "generate", lambda s, c: gen(s, c, stop_after=3))
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(ra.run_config("C0", seeds, {i: None for i in range(6)}, tmp_path))
    assert not (tmp_path / "questions_C0.jsonl").exists()
    assert len(ra._read_results(tmp_path / "questions_C0.partial.jsonl")) == 3
    calls.clear()
    monkeypatch.setattr(ra, "generate", lambda s, c: gen(s, c))
    res = asyncio.run(ra.run_config("C0", seeds, {i: None for i in range(6)}, tmp_path))
    assert sorted(calls) == [3, 4, 5] and [m["seed_chunk"] for _, m in res] == list(range(6))
    assert (tmp_path / "questions_C0.jsonl").exists() and not (tmp_path / "questions_C0.partial.jsonl").exists()
    calls.clear()
    asyncio.run(ra.run_config("C0", seeds, {}, tmp_path))      # đã xong: không sinh lại
    assert calls == []


def test_key_length_rank_balances_key_position():
    """Sau G1 (15/11): key không còn bị dồn về phương án ngắn nhất; hạng độ dài rút ngẫu nhiên theo key."""
    from app.generation import selector

    assert selector.rank_ok("a b c", ["a", "a b c d", "a b c d e"], 1)          # key đứng thứ 2 theo độ dài
    assert not selector.rank_ok("a b c", ["a", "a b c d", "a b c d e"], 0)
    assert selector.rank_ok("a b", ["a b", "x y", "a b c"], 0) and selector.rank_ok("a b", ["a b", "x y", "a b c"], 2)
    # mọi ứng viên đều dài hơn key → không thể đặt key dài nhất: lấy hạng khả thi gần nhất
    texts = ["a b c d", "a b c d e", "a b c d e f", "x y z w"]
    assert selector.feasible_target("k", texts) == 0
    # Trên nhiều câu, hạng mục tiêu phân bố đều 0..3 và bộ được chọn đặt key đúng hạng đó
    targets = []
    for i in range(200):
        key = " ".join(["w"] * 4) + f" k{i}"                                         # key 5 từ
        pool = [" ".join(["d"] * n) for n in (3, 4, 5, 6, 6, 7)]
        chosen, info = selector.select(0.0, [-1.0] * 6, "entropy", 0.0, texts=pool, key_text=key)
        assert "rank" in info["form_level"]
        assert selector.rank_ok(key, [pool[j] for j in chosen], info["key_len_target"])
        targets.append(info["key_len_target"])
    assert all(25 <= targets.count(r) <= 75 for r in range(4))


def test_reselect_rewrites_from_backup(tmp_path):
    from eval.v2 import reselect

    cands = [{"text": t, "score": s, "rejected_at": None, "error_type": e, "source": "llm"}
             for t, s, e in [("một", 1.0, "dao_nhan_qua"), ("hai ba bốn", 0.9, "sai_mot_chi_tiet"),
                             ("năm sáu bảy tám", 0.8, "khai_quat_qua_muc"), ("chín mười", 0.7, "dao_nhan_qua")]]
    rec = {"question": {"stem": "?", "answer": "đáp án đúng", "distractors": ["một", "hai ba bốn", "chín mười"]},
           "meta": {"seed_chunk": 1, "passed": True,
                    "v2": {"selection": {"key_score": 3.0, "mode": "entropy", "delta": 0.15}, "candidates": cands,
                           "picked": []}}}
    (tmp_path / "questions_C5.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    import sys
    argv = sys.argv
    sys.argv = ["x", "--results", str(tmp_path)]
    try:
        reselect.main()
        reselect.main()                                            # chạy lại: luôn từ bản cũ, kết quả như nhau
    finally:
        sys.argv = argv
    new = json.loads((tmp_path / "questions_C5.jsonl").read_text(encoding="utf-8"))
    assert (tmp_path / "questions_C5.truoc_chon_lai.jsonl").exists()
    assert len(new["question"]["distractors"]) == 3 and new["meta"]["v2"]["selection"]["reselected"]
    assert {p["text"] for p in new["meta"]["v2"]["picked"]} == set(new["question"]["distractors"])
