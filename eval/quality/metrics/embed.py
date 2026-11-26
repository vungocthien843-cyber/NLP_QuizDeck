"""Lớp A, mục 4.2 của đặc tả: chỉ số dùng embedding (bge-m3 dense, đã có trong container API) và A13.

Mỗi phương án được mã hoá hai dạng: đứng riêng (option) và kèm câu hỏi (stem + " " + option); báo cáo cả hai.

Hiệu chỉnh ngưỡng (cùng một bộ ngưỡng cho mọi phiên bản, tính trên toàn bộ câu của mọi phiên bản):
- E3 lạc đề, `topic_tau: auto`: phân bố "không liên quan" = cos(đáp án nhiễu, slide của CÂU KHÁC). τ = phân vị
  topic_null_q của phân bố đó. Đáp án nhiễu lạc đề khi nó không gần slide của chính nó hơn mức nó gần một slide
  bất kỳ khác. (τ = 0,3 của đặc tả không dùng được với bge-m3: mọi cos đều > 0,3.)
- E2 dạng kèm câu hỏi, `band_stem: auto`: ghép câu hỏi làm mọi cos dồn về khoảng 0,9, nên dải [a, b] không áp
  dụng được. Dải của dạng này lấy theo cùng phân vị mà a, b chiếm trong phân bố của dạng đứng riêng.

Lưu ý khi diễn giải: bge-m3 cùng họ với bộ xếp hạng bge-reranker mà V2 dùng để chọn bộ 3, nên E1/E2 có phần
"V2 tự chấm mình".
"""
from itertools import combinations

import numpy as np

from eval.quality.common import distractors, key_text

PER_ITEM_COLUMNS = {
    "E1_cos_d_key": ("TB cos(đáp án nhiễu, key), phương án đứng riêng", "D1", "trong [a, b]"),
    "E1_cos_d_key_stem": ("TB cos(đáp án nhiễu, key), kèm câu hỏi", "D1", "trong [a, b]"),
    "E2_in_band": ("Tỉ lệ đáp án nhiễu có a ≤ cos(d, key) ≤ b", "D1, K2", "cao"),
    "E2_in_band_stem": ("Như E2, kèm câu hỏi (dải theo phân vị)", "D1, K2", "cao"),
    "E3_off_topic": ("Tỉ lệ đáp án nhiễu lạc đề (cos(d, slide) < τ)", "D1, D2", "thấp"),
    "E4_dup_options": ("Có cặp đáp án nhiễu cos > 0,9", "D6", "thấp"),
}


def _encoder():
    from app.retrieval.embedder import get_embedder

    emb = get_embedder()

    def encode(texts: list[str]) -> np.ndarray:
        vecs = np.stack([r.dense for r in emb.encode(texts)]).astype(np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-12)
    return encode


def raw_similarities(items: list[dict], encode=None) -> list[dict]:
    """Các cos thô của từng câu (mã hoá một lần cho mọi phiên bản)."""
    encode = encode or _encoder()
    texts: list[str] = []
    index: dict[str, int] = {}

    def slot(t: str) -> int:            # văn bản trùng (cùng slide, cùng câu hỏi) chỉ mã hoá một lần
        if t not in index:
            index[t] = len(texts)
            texts.append(t)
        return index[t]
    plan = []
    for it in items:
        key, dis = key_text(it), distractors(it)
        plan.append({"key": slot(key), "key_s": slot(f"{it['stem']} {key}"),
                     "dis": [slot(d) for d in dis], "dis_s": [slot(f"{it['stem']} {d}") for d in dis],
                     "ctx": slot(it.get("source_context") or it["stem"]), "stem": slot(it["stem"])})
    V = encode(texts)
    ctx_ids = sorted({p["ctx"] for p in plan})
    C = V[ctx_ids]                                      # mọi slide khác nhau
    out = []
    for it, p in zip(items, plan, strict=True):
        own = ctx_ids.index(p["ctx"])
        d_ctx_all = V[p["dis"]] @ C.T                   # cos(d, mọi slide)
        out.append({
            "item_id": it["item_id"], "version": it["version"], "stem_vec": V[p["stem"]],
            "d_key": [float(V[d] @ V[p["key"]]) for d in p["dis"]],
            "d_key_stem": [float(V[d] @ V[p["key_s"]]) for d in p["dis_s"]],
            "d_ctx": [float(x) for x in d_ctx_all[:, own]],
            "d_ctx_other": [float(x) for row in np.delete(d_ctx_all, own, axis=1) for x in row],
            "d_pair_max": max(float(V[x] @ V[y]) for x, y in combinations(p["dis"], 2)),
        })
    return out


def calibrate(raw: list[dict], th: dict) -> dict:
    plain = np.array([c for r in raw for c in r["d_key"]])
    stem = np.array([c for r in raw for c in r["d_key_stem"]])
    cal = {"band_low": th["band_low"], "band_high": th["band_high"]}
    if th.get("band_stem", "auto") == "auto":
        q_lo, q_hi = float((plain < th["band_low"]).mean()), float((plain <= th["band_high"]).mean())
        cal["band_stem_low"], cal["band_stem_high"] = float(np.quantile(stem, q_lo)), float(np.quantile(stem, q_hi))
        cal["band_stem_quantiles"] = (round(q_lo, 3), round(q_hi, 3))
    else:
        cal["band_stem_low"], cal["band_stem_high"] = th["band_stem"]
    if th["topic_tau"] == "auto":
        null = np.array([c for r in raw for c in r["d_ctx_other"]])
        cal["topic_tau"] = float(np.quantile(null, th["topic_null_q"])) if len(null) else None
    else:
        cal["topic_tau"] = float(th["topic_tau"])
    return cal


def per_item(r: dict, cal: dict, th: dict, *, band_low=None, band_high=None, tau=None) -> dict:
    a, b = band_low if band_low is not None else cal["band_low"], band_high if band_high is not None else cal["band_high"]
    tau = tau if tau is not None else cal["topic_tau"]
    sa, sb = cal["band_stem_low"], cal["band_stem_high"]
    n = len(r["d_key"])
    return {
        "E1_cos_d_key": float(np.mean(r["d_key"])),
        "E1_cos_d_key_stem": float(np.mean(r["d_key_stem"])),
        "E2_in_band": sum(a <= c <= b for c in r["d_key"]) / n,
        "E2_in_band_stem": sum(sa <= c <= sb for c in r["d_key_stem"]) / n,
        "E3_off_topic": sum(c < tau for c in r["d_ctx"]) / n if tau is not None else None,
        "E4_dup_options": float(r["d_pair_max"] > th["dup_option_cos"]),
    }


def dup_stems(raw: list[dict], th: dict) -> tuple[dict, dict]:
    """A13 trong một phiên bản: tỉ lệ cặp câu hỏi cos > ngưỡng, và cờ theo item_id."""
    S = np.stack([r["stem_vec"] for r in raw]) if raw else np.zeros((0, 1))
    sim = S @ S.T
    n = len(raw)
    pairs = n * (n - 1) // 2
    hits = int(((sim > th["dup_stem_cos"]).sum() - n) // 2) if n else 0
    flags = {r["item_id"]: float(any(sim[i, j] > th["dup_stem_cos"] for j in range(n) if j != i))
             for i, r in enumerate(raw)}
    return {"A13_dup_pair_rate": hits / pairs if pairs else None, "A13_pairs": pairs}, flags
