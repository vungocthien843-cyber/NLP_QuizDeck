"""Đối chứng LLM trực tiếp (eval/baseline_llm.py): giữ câu hỏi/đáp án của V3, chỉ thay phương án nhiễu."""
import json

from eval import baseline_llm as b

SRC = {"item_id": "v3_1", "version": "V3", "chunk_id": 1, "doc_id": 2, "chapter": None, "slide": 3,
       "source_context": "slide", "concept": None, "stem": "Câu hỏi?", "bloom_target": "understand", "evidence": "e",
       "options": {"A": "sai 1", "B": "Đáp án đúng", "C": "sai 2", "D": "sai 3"}, "key": "B",
       "error_types": {"A": "x"}, "sources": {"A": "llm"}}


def test_parse_rejects_key_duplicates_and_short_lists():
    assert b.parse('{"distractors": ["a", "b", "c"]}', "k") == ["a", "b", "c"]
    assert b.parse('xx {"distractors": ["a", "A.", "đáp án đúng", "b", "c"]} yy', "Đáp án đúng") == ["a", "b", "c"]
    assert b.parse('{"distractors": ["a", "b"]}', "k") is None
    assert b.parse("không phải json", "k") is None


def test_make_item_keeps_stem_and_key_text():
    it = b.make_item(SRC, "LLM-GPT", "m", ["x", "y", "z"], 42)
    assert it["version"] == "LLM-GPT" and it["item_id"] == "llm-gpt_1"
    assert it["stem"] == SRC["stem"] and it["options"][it["key"]] == "Đáp án đúng"
    assert sorted(it["options"].values()) == sorted(["Đáp án đúng", "x", "y", "z"])
    assert it["error_types"] is None and it["sources"] is None


def test_run_resumes_retries_and_stops_on_daily_quota(tmp_path):
    out = tmp_path / "LLM-X_items.jsonl"
    items = [SRC, {**SRC, "chunk_id": 2}, {**SRC, "chunk_id": 3}]
    replies = iter(["hỏng", '{"distractors": ["a", "b", "c"]}', '{"distractors": ["d", "e", "f"]}'])
    st = b.run(items[:2], out, "LLM-X", "m", complete=lambda *a: next(replies), sleep=lambda s: None)
    assert st["moi"] == 2 and st["hong"] == 0
    st = b.run(items[:2], out, "LLM-X", "m", complete=lambda *a: 1 / 0, sleep=lambda s: None)
    assert st["co_san"] == 2 and st["moi"] == 0           # đã có thì không gọi lại

    def daily(*a):
        raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel")
    st = b.run(items, out, "LLM-X", "m", complete=daily, sleep=lambda s: None)
    assert "NGÀY" in st["dung"]
    assert [json.loads(x)["chunk_id"] for x in out.read_text(encoding="utf-8").splitlines()] == [1, 2]
