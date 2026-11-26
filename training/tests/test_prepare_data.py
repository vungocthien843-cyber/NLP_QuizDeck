import json

from training import prepare_data as pd
from training.common import key_recall, neg_terms, read_jsonl


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def test_answer_index_variants():
    opts = ["Hàn Quốc", "Việt Nam", "Nhật Bản", "Mỹ"]
    assert pd._answer_index(0, opts) == 0
    assert pd._answer_index("2", opts) == 2
    assert pd._answer_index("B", opts) == 1
    assert pd._answer_index("Đáp án D", opts) == 3
    assert pd._answer_index("nhật bản", opts) == 2
    assert pd._answer_index(7, opts) is None


def test_race_format_expands_questions():
    raw = {"id": "a1", "article": "Bài đọc.", "questions": ["Q1?", "Q2?"],
           "options": [["A. x", "B. y", "C. z", "D. t"], ["m", "n", "p"]], "answers": ["B", "C"]}
    m = pd.to_mcqs(raw, "train")
    assert len(m) == 2
    assert m[0]["options"] == ["x", "y", "z", "t"] and m[0]["answer_idx"] == 1
    assert m[1]["answer_idx"] == 2 and m[1]["group"] == "a1"


def test_copy_filter_and_neg_terms():
    assert key_recall("TF–IDF (Term Frequency–Inverse Document Frequency)", "TF-IDF") == 1.0
    assert key_recall("Bag-of-Words", "TF-IDF") == 0.0
    # chỉ giữ âm tiết nội dung không có trong câu hỏi
    assert neg_terms("Mô hình Transformer dùng self-attention", "Mô hình nào dùng cơ chế attention?") == [
        "transformer", "dùng", "self"] or "transformer" in neg_terms(
        "Mô hình Transformer dùng self-attention", "Mô hình nào dùng cơ chế attention?")


def test_select_context_keeps_relevant_sentences():
    ctx = " ".join(f"Câu thừa số {i} nói về chuyện khác." for i in range(60)) + " TF-IDF gán trọng số cho từ hiếm."
    out = pd.select_context(ctx, "Kỹ thuật nào gán trọng số cho từ hiếm?", "TF-IDF", max_words=40)
    assert "TF-IDF gán trọng số" in out
    assert len(out.split()) <= 48


def test_end_to_end(tmp_path):
    vs = [{"context": f"Đoạn {i} nói về Hàn Quốc và Seoul.", "question": f"Câu {i} ở nước nào?",
           "questiontype": "fact_check", "choices": ["Hàn Quốc", "Việt Nam", "Nhật Bản", "Mỹ"],
           "correctchoice": 0} for i in range(30)]
    vs.append({"context": "x", "question": "q?", "choices": ["Tất cả đều đúng", "b", "c", "d"], "correctchoice": 1})
    _write(tmp_path / "vsmrc" / "train.jsonl", vs[:25])
    _write(tmp_path / "vsmrc" / "test.jsonl", vs[25:])
    vi = [{"id": f"art{i}", "article": f"Bài đọc số {i} kể chuyện con mèo.",
           "questions": ["Con gì?"], "options": [["Mèo", "Chó", "Gà", "Mèo con"]], "answers": ["A"]}
          for i in range(20)]
    _write(tmp_path / "vimmrc2" / "data.json", vi)
    bank = [{"id": i, "group": f"doc{i % 5}", "context": f"Slide {i}: TF-IDF và BM25.",
             "question": f"Kỹ thuật nào số {i}?", "choices": ["TF-IDF", "BM25", "Word2Vec", "One-hot"],
             "correctchoice": 0, "questiontype": "remember", "reviewed": i % 2 == 0} for i in range(40)]
    _write(tmp_path / "bank.jsonl", bank)

    out = tmp_path / "out"
    pd.main(["--vsmrc", str(tmp_path / "vsmrc"), "--vimmrc2", str(tmp_path / "vimmrc2"),
             "--bank", str(tmp_path / "bank.jsonl"), "--out", str(out)])
    stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert stats["loc"]["vsmrc"]["bo_phuong_an_bi_cam"] == 1
    assert stats["loc"]["vsmrc"]["giu_lai"] == 30
    assert len(read_jsonl(out / "test_vsmrc_q.jsonl")) == 5            # giữ đúng tập test gốc
    rows = read_jsonl(out / "stage1_train.jsonl")
    assert all(r["distractor"] != r["answer"] for r in rows)
    assert {"question", "answer", "distractor", "context", "neg_terms", "other_distractors"} <= set(rows[0])
    # "Mèo con" chứa trọn đáp án "Mèo" → bị loại vì chép đáp án
    vi_rows = [r for r in rows if r["source"] == "vimmrc2"]
    assert vi_rows and all(r["distractor"] != "Mèo con" for r in vi_rows)
    # ngân hàng: 2 bài học làm test, không bài nào vừa ở test vừa ở train
    test_groups = {r["group"] for r in read_jsonl(out / "test_bank_q.jsonl")}
    train_groups = {r["group"] for r in read_jsonl(out / "stage2_train.jsonl")}
    assert len(test_groups) == 2 and not (test_groups & train_groups)


def test_bank_reviewed_only(tmp_path):
    bank = [{"id": i, "group": f"doc{i % 3}", "context": "ctx", "question": f"q{i}?", "choices": ["a", "b", "c", "d"],
             "correctchoice": 0, "reviewed": i < 4} for i in range(10)]
    _write(tmp_path / "bank.jsonl", bank)
    pd.main(["--bank", str(tmp_path / "bank.jsonl"), "--out", str(tmp_path / "o"), "--bank-reviewed-only"])
    stats = json.loads((tmp_path / "o" / "stats.json").read_text(encoding="utf-8"))
    assert stats["loc"]["bank"]["giu_lai"] == 4
