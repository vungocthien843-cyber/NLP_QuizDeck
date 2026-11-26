"""Lớp A, mục 4.1 của đặc tả: chỉ số theo luật và thống kê, không cần mô hình.

per_item(item, cfg) trả các cột của một câu; set_level(items, cfg) trả các chỉ số tính trên cả tập (A11, A12).
Với chỉ số "key có phải phương án nổi bật nhất" (A1, A4, A7, A10): hoà thì chia đều (common.tie_share),
mức ngẫu nhiên đúng 25%.
"""
import re
from collections import Counter
from difflib import SequenceMatcher
from itertools import permutations

from eval.quality.common import (LETTERS, content_tokens, distractors, key_text, nfc, rouge_l_precision,
                                 syllables, tie_share, words)

# A5: đặc tả + "bất kể" (hay gặp ở đáp án nhiễu do LLM sinh). "chỉ" đứng riêng là tuyệt đối, "chỉ số/ra..." thì không.
ABSOLUTE = re.compile(
    r"(?<!\w)(luôn luôn|luôn|không bao giờ|chẳng bao giờ|tất cả|mọi|duy nhất|hoàn toàn|bất kể|chỉ có|"
    r"chỉ(?!\s+(?:số|tiêu|định|ra|dẫn|thị|mục|thông|huy|đạo|báo|trích|rõ))(?!\w))(?!\w)")
ALL_NONE = re.compile(r"tất cả các (đáp án|phương án)|cả [a-d], [a-d]|không có (đáp án|phương án) nào|đều đúng|đều sai")
SLIDE_REF = re.compile(r"(?<!\w)(slide|hình trên|hình dưới|bảng trên|bảng dưới|ví dụ trên|như đã trình bày)(?!\w)")

PER_ITEM_COLUMNS = {
    # cột: (mô tả, mã lỗi, mục tiêu)
    "A1_key_longest": ("Key dài nhất trong 4 phương án", "K3", "≈ 0,25"),
    # Thêm ngoài đặc tả: lọc độ dài quá tay làm key thành phương án NGẮN nhất, cũng là một dấu hiệu để đoán
    "A1b_key_shortest": ("Key ngắn nhất trong 4 phương án", "K3", "≈ 0,25"),
    "A2_key_len_ratio": ("len(key) / TB len(đáp án nhiễu)", "K3", "≈ 1,0"),
    "A3_len_violation": ("max(len)/min(len) > 1,5", "D3", "thấp"),
    "A4_stem_overlap_cue": ("Key trùng từ với câu hỏi nhiều nhất", "S3", "≈ 0,25"),
    "A5_absolute_share": ("Tỉ lệ đáp án nhiễu có từ tuyệt đối", "D5", "thấp"),
    "A6_all_none": ("Có phương án 'tất cả/không có'", "D7", "0"),
    "A7_key_closest_to_slide": ("Key giống slide nhất (ROUGE-L)", "K4", "≈ 0,25"),
    "A8_stem_rouge": ("ROUGE-L(stem, slide)", "C2", "thấp"),
    "A8_stem_copied": ("ROUGE-L(stem, slide) > 0,7", "C2", "thấp"),
    "A9_slide_ref": ("Tham chiếu slide/hình", "C4", "0"),
    "A10_key_convergent": ("Key là điểm hội tụ của các phương án", "D4", "≈ 0,25"),
}


def per_item(item: dict, cfg: dict) -> dict:
    th = cfg["thresholds"]
    opts = [item["options"][k] for k in LETTERS]
    ki = LETTERS.index(item["key"])
    key, dis = key_text(item), distractors(item)
    lens = [words(o) for o in opts]
    stem_tok = set(content_tokens(item["stem"]))
    ctx = item.get("source_context") or ""
    tok_sets = [set(content_tokens(o)) for o in opts]
    convergence = [sum(len(tok_sets[i] & tok_sets[j]) for j in range(4) if j != i) for i in range(4)]
    low = [nfc(o).lower() for o in opts]
    stem_rouge = rouge_l_precision(item["stem"], ctx) if ctx else None
    return {
        "A1_key_longest": tie_share(lens, ki),
        "A1b_key_shortest": tie_share([-x for x in lens], ki),
        "A2_key_len_ratio": words(key) / (sum(words(d) for d in dis) / len(dis) or 1),
        "A3_len_violation": float(max(lens) / max(min(lens), 1) > th["length_ratio_max"]),
        "A4_stem_overlap_cue": tie_share([len(stem_tok & s) for s in tok_sets], ki),
        "A5_absolute_share": sum(bool(ABSOLUTE.search(nfc(d).lower())) for d in dis) / len(dis),
        "A6_all_none": float(any(ALL_NONE.search(t) for t in low)),
        "A7_key_closest_to_slide": tie_share([rouge_l_precision(o, ctx) for o in opts], ki) if ctx else None,
        "A8_stem_rouge": stem_rouge,
        "A8_stem_copied": float(stem_rouge > th["stem_copy"]) if stem_rouge is not None else None,
        "A9_slide_ref": float(bool(SLIDE_REF.search(nfc(" ".join([item["stem"], *opts])).lower()))),
        "A10_key_convergent": tie_share(convergence, ki),
        "_len_ratio": max(lens) / max(min(lens), 1),     # cho phân tích độ nhạy của A3
    }


def _fuzzy_in(needle: list[str], hay: list[str], ratio: float) -> bool:
    """Chuỗi âm tiết needle có xuất hiện (gần đúng) trong hay: so với mọi cửa sổ cùng độ dài."""
    n = len(needle)
    if n == 0 or len(hay) < n:
        return False
    s = " ".join(needle)
    return any(SequenceMatcher(None, s, " ".join(hay[i:i + n])).ratio() >= ratio for i in range(len(hay) - n + 1))


def key_position(items: list[dict]) -> dict:
    """A11: phân bố vị trí key, kiểm định chi-bình phương với phân bố đều (bậc tự do 3)."""
    from eval.quality.stats import chi2_uniform

    cnt = Counter(it["key"] for it in items)
    obs = [cnt.get(k, 0) for k in LETTERS]
    stat, p = chi2_uniform(obs)
    return {"A11_key_counts": "/".join(f"{k}{v}" for k, v in zip(LETTERS, obs)), "A11_chi2": stat, "A11_p": p}


def cross_leak(items: list[dict], cfg: dict) -> tuple[dict, dict]:
    """A12: trong cùng một đề (cùng bài), tỉ lệ cặp (i, j) mà đáp án câu i lộ trong câu hỏi câu j.
    Trả (chỉ số tập, cờ theo item_id)."""
    th = cfg["thresholds"]
    groups: dict = {}
    for it in items:
        groups.setdefault(it.get("doc_id"), []).append(it)
    pairs = leaks = 0
    flag = {it["item_id"]: 0.0 for it in items}
    for group in groups.values():
        for a, b in permutations(group, 2):
            key = syllables(key_text(a))
            if len(key) < th["leak_min_syllables"]:
                continue
            pairs += 1
            if _fuzzy_in(key, syllables(b["stem"]), th["leak_ratio"]):
                leaks += 1
                flag[a["item_id"]] = 1.0
    return {"A12_leak_pair_rate": leaks / pairs if pairs else None, "A12_pairs": pairs}, flag
