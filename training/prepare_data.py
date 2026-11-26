"""Chuẩn hoá các bộ trắc nghiệm tiếng Việt về một định dạng JSONL chung để fine-tune mô hình sinh đáp án nhiễu.

Nguồn (đường dẫn có thể là file hoặc thư mục; nhận .json / .jsonl / .csv / .parquet):
  --vsmrc    VSMRC/mrc trên Hugging Face: train.jsonl, test.jsonl, ... mỗi dòng
             {context, question, questiontype, choices: [str], correctchoice: int}
  --vimmrc2  ViMMRC 2.0 (dạng RACE: article + questions + options + answers, hoặc dạng phẳng)
  --vimmrc1  ViMMRC 1.0 (như trên)
  --bank     JSONL xuất bởi training/export_bank.py (ngân hàng câu hỏi môn NLP)

Đầu ra trong --out:
  stage1_train.jsonl, stage1_dev.jsonl   một dòng = (câu hỏi, MỘT đáp án nhiễu)      — giai đoạn 1
  stage1_dev_q.jsonl                       một dòng = một câu hỏi, đủ các đáp án nhiễu  — đo khi sinh
  test_<nguồn>_q.jsonl                     tập test từng nguồn (một dòng = một câu hỏi)
  stage2_train.jsonl, stage2_dev.jsonl, stage2_dev_q.jsonl                              — giai đoạn 2
  stats.json                               thẻ dữ liệu cho báo cáo

Chạy: python -m training.prepare_data --vsmrc data/raw/vsmrc --bank data/raw/bank.jsonl --out data/processed
"""
import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

from training.common import (
    LETTERS, bucket, has_banned, key_recall, neg_terms, nfc, normalize_text, stable_hash, syllables, write_jsonl,
)

COPY_THRESHOLD = 0.95
CONTEXT_KEYS = ("context", "article", "passage", "text", "paragraph", "segment", "segmenttext", "content", "story")
QUESTION_KEYS = ("question", "query", "stem", "questiontext")
OPTION_KEYS = ("choices", "options", "candidates", "answers_list", "option_list")
ANSWER_KEYS = ("correctchoice", "answer", "label", "correct", "correct_answer", "answer_index", "answer_idx",
               "correct_choice", "gold", "answers")
TYPE_KEYS = ("questiontype", "question_type", "type", "q_type")
GROUP_KEYS = ("group", "article_id", "segment_id", "doc_id", "document_id", "passage_id", "story_id", "id")
SPLIT_ALIASES = {"train": "train", "training": "train", "dev": "dev", "val": "dev", "valid": "dev",
                 "validation": "dev", "test": "test", "testing": "test"}


# ---------- Đọc file ----------
def _split_hint(path: Path) -> str | None:
    for part in reversed(re.split(r"[\\/_.\-\s]+", str(path).lower())):
        if part in SPLIT_ALIASES:
            return SPLIT_ALIASES[part]
    return None


def _read_file(path: Path) -> list[dict]:
    suf = path.suffix.lower()
    if suf == ".jsonl":
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    if suf == ".json":
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:            # một số bộ đặt đuôi .json nhưng thực ra là JSONL
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(data, dict):
            for k in ("data", "items", "records", "examples"):
                if isinstance(data.get(k), list):
                    return data[k]
            return [data]
        return data
    if suf == ".csv":
        with path.open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    if suf == ".parquet":
        import pandas as pd
        return pd.read_parquet(path).to_dict(orient="records")
    return []


def load_any(path: str | Path) -> list[tuple[dict, str | None]]:
    path = Path(path)
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.suffix.lower() in (".json", ".jsonl", ".csv", ".parquet"))
    out = []
    for f in files:
        hint = _split_hint(f.relative_to(path) if path.is_dir() else f.name)
        out += [(r, hint) for r in _read_file(f) if isinstance(r, dict)]
    return out


# ---------- Nhận diện trường ----------
def _first(d: dict, keys) -> object:
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k in low and low[k] not in (None, ""):
            return low[k]
    return None


def _as_text(x) -> str:
    if isinstance(x, dict):
        x = _first(x, ("text", "content", "value", "option", "choice"))
    return nfc(str(x)) if x is not None else ""


def _options(d: dict) -> list[str]:
    opts = _first(d, OPTION_KEYS)
    if isinstance(opts, str):
        try:
            opts = json.loads(opts)
        except json.JSONDecodeError:
            opts = None
    if isinstance(opts, dict):
        opts = [opts[k] for k in sorted(opts)]
    if isinstance(opts, list) and opts and not isinstance(opts[0], list):
        return [_as_text(o) for o in opts]
    low = {str(k).lower(): v for k, v in d.items()}
    for pattern in ("{}", "option_{}", "option{}", "choice_{}", "choice{}", "opt_{}"):
        found = [low.get(pattern.format(c)) for c in "abcd"] or []
        if all(v not in (None, "") for v in found[:2]):
            return [_as_text(v) for v in found if v not in (None, "")]
    return []


def _answer_index(raw, options: list[str]) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and not math.isnan(raw):
        i = int(raw)
        return i if 0 <= i < len(options) else None
    s = nfc(str(raw))
    if s.isdigit():
        i = int(s)
        return i if 0 <= i < len(options) else None
    if len(s) == 1 and s.upper() in LETTERS[:len(options)]:
        return LETTERS.index(s.upper())
    m = re.fullmatch(r"(?i)(?:đáp án|phương án|option)?\s*([A-H])[.)]?", s)
    if m and LETTERS.index(m.group(1).upper()) < len(options):
        return LETTERS.index(m.group(1).upper())
    norm = normalize_text(s)
    for i, o in enumerate(options):
        if normalize_text(o) == norm:
            return i
    return None


_PREFIX = re.compile(r"^\s*(?:[A-Ha-h]|\d)[.)]\s+")


def _clean_option(o: str) -> str:
    return nfc(_PREFIX.sub("", o))


def to_mcqs(raw: dict, hint: str | None) -> list[dict]:
    """Một bản ghi gốc → danh sách câu {context, question, options, answer_idx, q_type, group, split}."""
    context = _first(raw, CONTEXT_KEYS)
    group = _first(raw, GROUP_KEYS)
    split = SPLIT_ALIASES.get(str(_first(raw, ("split",)) or "").lower()) or hint
    q_type = _first(raw, TYPE_KEYS)
    questions = raw.get("questions")
    items: list[dict] = []
    if isinstance(questions, list) and questions and isinstance(questions[0], str):
        # dạng RACE: questions[i], options[i], answers[i]
        opts_all, ans_all = raw.get("options") or [], raw.get("answers") or []
        for i, q in enumerate(questions):
            opts = [_as_text(o) for o in (opts_all[i] if i < len(opts_all) else [])]
            items.append({"question": q, "options": opts, "answer": ans_all[i] if i < len(ans_all) else None})
    elif isinstance(questions, list):
        for q in questions:
            if isinstance(q, dict):
                opts = _options(q)
                items.append({"question": _first(q, QUESTION_KEYS), "options": opts,
                              "answer": _first(q, ANSWER_KEYS), "q_type": _first(q, TYPE_KEYS)})
    else:
        opts = _options(raw)
        items.append({"question": _first(raw, QUESTION_KEYS), "options": opts, "answer": _first(raw, ANSWER_KEYS)})

    out = []
    ctx = nfc(str(context)) if context else ""
    gid = str(group) if group is not None else stable_hash(ctx or json.dumps(raw, ensure_ascii=False))
    for it in items:
        options = [_clean_option(o) for o in it["options"]]
        out.append({"context": ctx, "question": nfc(str(it["question"] or "")), "options": options,
                    "answer_idx": _answer_index(it["answer"], options),
                    "q_type": str(it.get("q_type") or q_type or ""), "group": gid, "split": split})
    return out


# ---------- Cắt ngữ cảnh ----------
_SENT = re.compile(r"(?<=[.!?…;:])\s+|\n+|\s+[•\-–]\s+")


def select_context(context: str, question: str, answer: str, max_words: int) -> str:
    """Giữ các câu liên quan nhất tới (câu hỏi + đáp án) theo thứ tự gốc, tới tối đa max_words âm tiết.
    Điểm = số âm tiết nội dung chung, chia căn độ dài câu (ưu tiên câu ngắn mà trúng nhiều)."""
    if len(context.split()) <= max_words:
        return context
    sents = [s.strip() for s in _SENT.split(context) if s and s.strip()]
    keys = {t for t in syllables(f"{question} {answer}") if len(t) > 1}
    scored = []
    for i, s in enumerate(sents):
        toks = syllables(s)
        hit = sum(t in keys for t in toks)
        scored.append((hit / math.sqrt(len(toks) + 1), i, s, len(s.split())))
    keep, used = set(), 0
    for _, i, _, n in sorted(scored, key=lambda t: (-t[0], t[1])):
        if used + n > max_words and keep:
            continue
        keep.add(i)
        used += n
        if used >= max_words:
            break
    return " ".join(s for i, s in enumerate(sents) if i in keep)


# ---------- Làm sạch một câu ----------
def clean_mcq(m: dict, stats: Counter) -> dict | None:
    if not m["context"]:
        stats["bo_khong_co_ngu_canh"] += 1
        return None
    if not m["question"] or m["answer_idx"] is None or len(m["options"]) < 2:
        stats["bo_thieu_cau_hoi_hoac_dap_an"] += 1
        return None
    if any(has_banned(o) for o in m["options"]):
        stats["bo_phuong_an_bi_cam"] += 1
        return None
    answer = m["options"][m["answer_idx"]]
    distractors, seen = [], {normalize_text(answer)}
    for i, o in enumerate(m["options"]):
        if i == m["answer_idx"]:
            continue
        norm = normalize_text(o)
        if not norm or norm in seen:
            stats["bo_dap_an_nhieu_rong_hoac_trung"] += 1
            continue
        if key_recall(o, answer) >= COPY_THRESHOLD:
            stats["bo_dap_an_nhieu_chep_dap_an"] += 1
            continue
        seen.add(norm)
        distractors.append(o)
    if not distractors:
        stats["bo_khong_con_dap_an_nhieu"] += 1
        return None
    return {**m, "answer": answer, "distractors": distractors}


def question_row(m: dict, source: str, idx: int, max_words: int) -> dict:
    ctx = select_context(m["context"], m["question"], m["answer"], max_words)
    return {"id": f"{source}-{idx:06d}", "source": source, "split": m["split"], "group": f"{source}:{m['group']}",
            "q_type": m["q_type"], "question": m["question"], "answer": m["answer"],
            "distractors": m["distractors"], "context": ctx, "neg_terms": neg_terms(m["answer"], m["question"])}


def distractor_rows(q: dict):
    for j, d in enumerate(q["distractors"]):
        yield {"id": f"{q['id']}-d{j}", "source": q["source"], "split": q["split"], "group": q["group"],
               "q_type": q["q_type"], "question": q["question"], "answer": q["answer"], "distractor": d,
               "other_distractors": [x for x in q["distractors"] if x != d], "context": q["context"],
               "neg_terms": q["neg_terms"]}


# ---------- Chia tập ----------
def assign_splits(rows: list[dict], keep_given: bool, train=0.8, dev=0.1) -> None:
    for r in rows:
        if keep_given and r["split"] in ("train", "dev", "test"):
            continue
        b = bucket(r["group"])
        r["split"] = "train" if b < train else "dev" if b < train + dev else "test"
    if keep_given and not any(r["split"] == "dev" for r in rows):
        # bộ gốc không có tập dev: tách 10% nhóm của train làm dev
        for r in rows:
            if r["split"] == "train" and bucket("dev:" + r["group"]) < 0.1:
                r["split"] = "dev"


def split_bank(rows: list[dict], n_test_groups: int, test_docs=None, dev_docs=None) -> None:
    """Giữ riêng n_test_groups bài học làm test đúng miền; phần còn lại chia train/dev theo bài nếu đủ bài.
    Nếu chỉ định test_docs / dev_docs (id bài học) thì dùng đúng các bài đó, phần còn lại là train."""
    if test_docs or dev_docs:
        test_g = {f"doc{i}" for i in test_docs or []}
        dev_g = {f"doc{i}" for i in dev_docs or []}
        for r in rows:
            g = r["group"].split(":")[-1]          # "bank:doc17" → "doc17"
            r["split"] = "test" if g in test_g else "dev" if g in dev_g else "train"
        return
    groups = sorted({r["group"] for r in rows}, key=lambda g: stable_hash(g))
    test = set(groups[:n_test_groups]) if len(groups) > n_test_groups else set()
    rest = [g for g in groups if g not in test]
    by_group = len(rest) >= 4
    for r in rows:
        if r["group"] in test:
            r["split"] = "test"
        else:
            b = bucket(r["group"] if by_group else r["id"])
            r["split"] = "train" if b < 0.85 else "dev"


# ---------- Thống kê ----------
def _mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 1) if xs else 0.0


def describe(rows: list[dict]) -> dict:
    return {
        "so_cau": len(rows),
        "so_mau_dap_an_nhieu": sum(len(r["distractors"]) for r in rows),
        "so_nhom": len({r["group"] for r in rows}),
        "do_dai_tb_am_tiet": {
            "ngu_canh": _mean(len(r["context"].split()) for r in rows),
            "cau_hoi": _mean(len(r["question"].split()) for r in rows),
            "dap_an": _mean(len(r["answer"].split()) for r in rows),
            "dap_an_nhieu": _mean(len(d.split()) for r in rows for d in r["distractors"]),
        },
        "loai_cau": dict(Counter(r["q_type"] or "(không ghi)" for r in rows).most_common()),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vsmrc")
    ap.add_argument("--vimmrc2")
    ap.add_argument("--vimmrc1")
    ap.add_argument("--bank")
    ap.add_argument("--out", default="training/data/processed")
    ap.add_argument("--max-ctx-words", type=int, default=300)
    ap.add_argument("--bank-test-groups", type=int, default=2)
    ap.add_argument("--bank-test-docs", nargs="+", type=int, help="id bài học làm tập test của ngân hàng")
    ap.add_argument("--bank-dev-docs", nargs="+", type=int, help="id bài học làm tập dev của ngân hàng")
    ap.add_argument("--bank-reviewed-only", action="store_true",
                    help="giai đoạn 2 chỉ dùng câu đã được người chấm duyệt (trường reviewed của export_bank)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    stats: dict = {"nguon": {}, "loc": {}}
    seen_questions: set[str] = set()
    by_source: dict[str, list[dict]] = {}
    for source, path in (("vsmrc", args.vsmrc), ("vimmrc2", args.vimmrc2), ("vimmrc1", args.vimmrc1),
                         ("bank", args.bank)):
        if not path:
            continue
        counter: Counter = Counter()
        rows = []
        for raw, hint in load_any(path):
            if source == "bank" and args.bank_reviewed_only and not raw.get("reviewed"):
                counter["bo_chua_duoc_duyet"] += 1
                continue
            for m in to_mcqs(raw, hint):
                counter["doc_vao"] += 1
                m = clean_mcq(m, counter)
                if m is None:
                    continue
                key = stable_hash(normalize_text(m["question"]) + "|" + normalize_text(m["context"])[:500])
                if key in seen_questions:
                    counter["bo_trung_voi_nguon_khac"] += 1
                    continue
                seen_questions.add(key)
                rows.append(question_row(m, source, len(rows), args.max_ctx_words))
        if source == "bank":
            split_bank(rows, args.bank_test_groups, args.bank_test_docs, args.bank_dev_docs)
        else:
            assign_splits(rows, keep_given=(source == "vsmrc"))
        by_source[source] = rows
        counter["giu_lai"] = len(rows)
        stats["loc"][source] = dict(counter)
        stats["nguon"][source] = {s: describe([r for r in rows if r["split"] == s]) for s in ("train", "dev", "test")}
        print(f"{source}: đọc {counter['doc_vao']}, giữ {len(rows)} câu "
              + " ".join(f"{s}={sum(r['split'] == s for r in rows)}" for s in ("train", "dev", "test")))

    general = [r for s, rows in by_source.items() if s != "bank" for r in rows]
    bank = by_source.get("bank", [])
    written = {
        "stage1_train.jsonl": write_jsonl(out / "stage1_train.jsonl",
                                          (d for q in general if q["split"] == "train" for d in distractor_rows(q))),
        "stage1_dev.jsonl": write_jsonl(out / "stage1_dev.jsonl",
                                        (d for q in general if q["split"] == "dev" for d in distractor_rows(q))),
        "stage1_dev_q.jsonl": write_jsonl(out / "stage1_dev_q.jsonl", (q for q in general if q["split"] == "dev")),
    }
    for source, rows in by_source.items():
        name = f"test_{source}_q.jsonl"
        written[name] = write_jsonl(out / name, (q for q in rows if q["split"] == "test"))
    if bank:
        written["stage2_train.jsonl"] = write_jsonl(
            out / "stage2_train.jsonl", (d for q in bank if q["split"] == "train" for d in distractor_rows(q)))
        written["stage2_dev.jsonl"] = write_jsonl(
            out / "stage2_dev.jsonl", (d for q in bank if q["split"] == "dev" for d in distractor_rows(q)))
        written["stage2_dev_q.jsonl"] = write_jsonl(out / "stage2_dev_q.jsonl", (q for q in bank if q["split"] == "dev"))
    stats["file_ghi_ra"] = written
    stats["tham_so"] = {"max_ctx_words": args.max_ctx_words, "copy_threshold": COPY_THRESHOLD,
                        "bank_test_groups": args.bank_test_groups}
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(written, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
