"""Kiểm thử lớp S/J của eval/quality với mô hình giả (không gọi API). Chạy: python -m pytest -q tests/"""
import asyncio
import json

from eval.quality.metrics import llm_eval

ITEM = {"item_id": "t1", "stem": "Mô hình nào dùng phép đếm n-gram?", "key": "B", "bloom_target": "remember",
        "source_context": "Mô hình n-gram ước lượng xác suất bằng phép đếm.",
        "options": {"A": "Word2Vec", "B": "Mô hình n-gram", "C": "Transformer", "D": "LSTM"}}


def _letter_of(prompt: str, text: str) -> str:
    for line in prompt.splitlines():
        if line[:3] in ("A. ", "B. ", "C. ", "D. ") and line[3:].strip() == text:
            return line[0]
    return "A"


async def fake(model, prompt, temperature):
    if "câu hỏi đã bị ẩn" in prompt:                      # P6: luôn đoán A
        return json.dumps({"answer": "A"})
    if "Trả lời câu hỏi trắc nghiệm sau bằng hiểu biết" in prompt or "Dựa vào NGỮ CẢNH, trả lời" in prompt:
        return "```json\n" + json.dumps({"answer": _letter_of(prompt, "Mô hình n-gram")}) + "\n```"
    if '"supported"' in prompt:
        return json.dumps({"supported": "yes"})
    if "correct|incorrect|undetermined" in prompt:
        return json.dumps({"A": "incorrect", "B": "correct", "C": "incorrect", "D": "undetermined"})
    if "tối đa 20 từ" in prompt:
        return json.dumps({"answer": "mô hình n-gram"})
    if "Danh sách mã lỗi" in prompt:
        return json.dumps({"flaws": [{"code": "D2", "option": "C"}], "overall_usable": "minor_edit"})
    if "thang Bloom" in prompt:
        return json.dumps({"bloom": "remember"})
    raise AssertionError(prompt[:80])


def test_llm_layers(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_eval, "CACHE", tmp_path / "cache.jsonl")
    cfg = {"seed": 1, "eval_models": {"judge": "x/judge", "solvers": ["y/s1", "z/s2"]},
           "generator_models": ["openai/gen"], "eval_llm": {"runs": 2, "concurrency": 3, "cache": True}}
    rows = {"V": [{"item_id": "t1"}]}
    stats = asyncio.run(llm_eval.run_layers(rows, {"V": [ITEM]}, ["S", "J"], cfg, complete=fake))
    r = rows["V"][0]
    assert r["S8_open_book"] == 1.0 and r["S7_closed_book"] == 1.0
    assert 0.0 <= r["S6_options_only"] <= 1.0                 # đoán A trên thứ tự đã xáo
    assert r["J1_key_supported"] == 1.0
    assert r["J2_unique_correct"] == 0.0 and r["J2_multi_correct"] == 0.0   # D undetermined → không "duy nhất"
    assert r["J3_stem_standalone"] == 1.0 and r["J4_usable"] == 0.5 and r["J4_distractor_flaw"] == 1.0
    assert r["J5_bloom_match"] == 1.0
    assert stats["new_calls"] == 3 * 2 * 2 + 5                # 3 điều kiện × 2 solver × 2 lần + 5 prompt judge
    # chạy lại: lấy hết từ bộ đệm, không gọi mô hình
    rows2 = {"V": [{"item_id": "t1"}]}
    stats2 = asyncio.run(llm_eval.run_layers(rows2, {"V": [ITEM]}, ["S", "J"], cfg, complete=fake))
    assert stats2["new_calls"] == 0 and rows2["V"][0] == r


def test_render_keeps_json_braces():
    text = llm_eval.render("P1", ITEM, ITEM["options"])
    assert '{"supported"' in text and "Mô hình n-gram" in text and "{stem}" not in text


def test_failed_or_unreadable_calls_are_not_counted_as_wrong(monkeypatch, tmp_path):
    """Gọi lỗi / trả lời không đọc được không được tính là solver trả lời sai (14/11: "" in "ABCD" là True)."""
    monkeypatch.setattr(llm_eval, "CACHE", tmp_path / "c.jsonl")

    async def boom(model, prompt, temperature):
        raise RuntimeError("401")

    async def garbage(model, prompt, temperature):
        return "không biết"
    cfg = {"seed": 1, "eval_models": {"judge": "x/j", "solvers": ["y/s"]}, "eval_llm": {"runs": 1}}
    for fn in (boom, garbage):
        rows = {"V": [{"item_id": "t1"}]}
        asyncio.run(llm_eval.run_layers(rows, {"V": [ITEM]}, ["S"], {**cfg, "eval_llm": {"runs": 1, "cache": False}},
                                        complete=fn))
        assert rows["V"][0]["S8_open_book"] is None and rows["V"][0]["S6_options_only"] is None


def test_daily_quota_stops_model_and_minute_limit_retries(monkeypatch, tmp_path):
    """Gói miễn phí: 429 theo phút → chờ rồi thử lại; 429 theo NGÀY → dừng model đó, các lần gọi sau bỏ qua."""
    monkeypatch.setattr(llm_eval, "CACHE", tmp_path / "c.jsonl")
    n = {"x/j": 0, "y/s": 0}

    async def fake(model, prompt, temperature):
        n[model] += 1
        if model == "x/j":
            raise RuntimeError("RateLimitError 429: Quota exceeded GenerateRequestsPerDayPerProjectPerModel")
        if n[model] == 1:
            raise RuntimeError("RateLimitError 429: GenerateRequestsPerMinutePerProjectPerModel")
        return '{"answer": "B"}'
    cfg = {"seed": 1, "eval_models": {"judge": "x/j", "solvers": ["y/s"]},
           "eval_llm": {"runs": 1, "cache": False, "retry_wait": 0}}
    rows = {"V": [{"item_id": "t1"}, {"item_id": "t2"}]}
    items = {"V": [ITEM, {**ITEM, "item_id": "t2"}]}
    stats = asyncio.run(llm_eval.run_layers(rows, items, ["S", "J"], cfg, complete=fake))
    assert stats["quota_exhausted"] == ["x/j"] and n["x/j"] == 1         # chỉ gọi judge đúng 1 lần
    assert stats["skipped_calls"] >= 1
    assert rows["V"][0]["S8_open_book"] is not None                       # solver vẫn chấm sau khi chờ


def test_budget_cap_and_judge_prompt_subset(monkeypatch, tmp_path):
    """Trần chi phí: chạm trần thì bỏ qua các lần gọi còn lại; giám khảo chỉ chạy prompt được chọn."""
    monkeypatch.setattr(llm_eval, "CACHE", tmp_path / "c.jsonl")
    seen = []

    async def fake(model, prompt, temperature):
        seen.append(prompt[:20])
        llm_eval.USAGE["usd"] += 0.01
        return '{"answer": "B"}'
    monkeypatch.setitem(llm_eval.USAGE, "usd", 0.0)
    cfg = {"seed": 1, "eval_models": {"judge": "x/j", "solvers": ["y/s"]},
           "eval_llm": {"runs": 1, "cache": False, "concurrency": 1, "max_usd": 0.025, "judge_prompts": ["P2"]}}
    rows = {"V": [{"item_id": f"t{i}"} for i in range(3)]}
    items = {"V": [{**ITEM, "item_id": f"t{i}"} for i in range(3)]}
    stats = asyncio.run(llm_eval.run_layers(rows, items, ["S", "J"], cfg, complete=fake))
    assert stats["budget_hit"] and len(seen) == 3 and stats["skipped_calls"] > 0
    stats2 = asyncio.run(llm_eval.run_layers({"V": [{"item_id": "z"}]}, {"V": [{**ITEM, "item_id": "z"}]}, ["J"],
                                             {**cfg, "eval_llm": {**cfg["eval_llm"], "max_usd": None}}, complete=fake))
    assert stats2["new_calls"] == 1                               # chỉ P2, không phải 5 prompt
