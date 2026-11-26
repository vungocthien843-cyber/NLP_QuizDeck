"""Bước 6 của pipeline v2: chấm điểm phương án và chọn bộ 3 đáp án nhiễu (K4).

Cực đại entropy theo Chung et al. 2020 (BDG_EM), thêm ràng buộc mà bài gốc thiếu: đáp án đúng phải được
"người giải" chọn nhiều nhất VÀ hơn phương án sai mạnh nhất ít nhất δ. Không có ràng buộc này, bộ entropy cao
nhất có thể chứa một phương án thực ra cũng đúng (ví dụ BM25 trong docs: bai-2 mục 5.1).

Chấm điểm một lần cho cả đáp án đúng và mọi ứng viên (điểm s_o, coi như logit), rồi suy xác suất trong từng bộ
theo tiên đề lựa chọn Luce:  p_S(o) = exp(s_o) / Σ_{o' ∈ S ∪ {A}} exp(s_o').  Nhờ vậy duyệt C(n,3) bộ mà không
phải gọi model giải cho từng bộ.

Ràng buộc hình thức (khi truyền texts, chỉ cho chế độ entropy*): bộ đạt khi độ dài 4 phương án không lệch quá
set_length_ratio lần và key không phải "điểm hội tụ" (phương án chung nhiều từ với các phương án khác nhất, đoán
được mà không cần kiến thức: Haladyna et al. 2002). Không bộ nào đạt cả hai thì nới dần: chỉ giữ ràng buộc độ dài,
rồi chỉ giữ ràng buộc hội tụ, cuối cùng bỏ cả hai; mức đã dùng ghi ở form_level (both | length | convergence | none).

Hạng độ dài của key (distractor.key_length_rank, thêm sau G1): mỗi câu rút một hạng mục tiêu 0..3 (0 = ngắn nhất)
theo chính key, rồi ưu tiên bộ mà key đứng đúng hạng đó (mức có hậu tố "+rank"). Nhờ vậy key ngắn nhất, dài nhất
hay ở giữa đều khoảng 25%: không còn mẹo "chọn câu dài/ngắn nhất", cũng không sinh mẹo ngược "chọn câu ở giữa".
"""
import asyncio
import logging
import math
import random
from collections import Counter
from itertools import combinations

from app.config import get_config
from app.generation.filters import syllables
from app.prompts import UNCLEAR

_STOP = frozenset("và của là các những một có cho được trong với để khi thì này đó theo từ đến về như mà nên vì do "
                  "bị đã sẽ đang cũng rất hơn nhất lại ra vào trên dưới nào gì sao hay hoặc nếu ở tại bằng qua sau "
                  "trước rằng việc cách điều sự cái còn đều vẫn chỉ mỗi từng cả".split())


def _tokens(text: str) -> set[str]:
    return {t for t in syllables(text) if t not in _STOP}


def form_ok(key_text: str, texts: list[str], length_ratio: float, avoid_convergence: bool) -> bool:
    opts = [key_text, *texts]
    if length_ratio:
        lens = [max(len(o.split()), 1) for o in opts]
        if max(lens) / min(lens) > length_ratio:
            return False
    if avoid_convergence:
        toks = [_tokens(o) for o in opts]
        conv = [sum(len(toks[i] & toks[j]) for j in range(len(opts)) if j != i) for i in range(len(opts))]
        if conv[0] > max(conv[1:]):          # key là điểm hội tụ duy nhất (hoà thì không tính)
            return False
    return True

def target_rank(key_text: str) -> int:
    """Hạng độ dài mục tiêu của key (0 = ngắn nhất … 3 = dài nhất), cố định theo key để chạy lại cho cùng kết quả."""
    return random.Random(f"len-rank:{key_text}").randrange(4)


def feasible_target(key_text: str, texts: list[str], k: int = 3) -> int:
    """Hạng mục tiêu rút ngẫu nhiên; nếu kho ứng viên không thể đặt key ở hạng đó (ví dụ mọi ứng viên đều dài hơn
    key thì key không thể dài nhất) thì lấy hạng khả thi gần nhất, hoà thì lấy hạng dài hơn. Không làm vậy thì kho
    lệch độ dài (ứng viên LLM thường dài hơn key) kéo key về phía ngắn nhất."""
    want = target_rank(key_text)
    feasible = {r for S in combinations(range(len(texts)), k) for r in range(4)
                if rank_ok(key_text, [texts[i] for i in S], r)}
    return min(feasible, key=lambda r: (abs(r - want), -r)) if feasible else want


def rank_ok(key_text: str, texts: list[str], target: int) -> bool:
    """Key đứng ở hạng target theo số từ; hoà độ dài thì mọi hạng trong khoảng hoà đều tính là đạt."""
    k = max(len(key_text.split()), 1)
    lens = [max(len(t.split()), 1) for t in texts]
    lo = sum(x < k for x in lens)
    hi = lo + sum(x == k for x in lens)
    return lo <= target <= hi


log = logging.getLogger(__name__)


# ---------- Chọn bộ (hàm thuần, dễ kiểm thử) ----------
def softmax(z: list[float]) -> list[float]:
    m = max(z)
    e = [math.exp(x - m) for x in z]
    s = sum(e)
    return [x / s for x in e]


def entropy(p: list[float]) -> float:
    return -sum(x * math.log2(x) for x in p if x > 0)


def evaluate_set(key_score: float, scores: list[float]) -> dict:
    p = softmax([key_score, *scores])
    strongest = max(p[1:])
    return {"probs": [round(x, 4) for x in p], "entropy": round(entropy(p), 4),
            "margin": round(p[0] - strongest, 4), "key_wins": p[0] >= strongest}


def diverse_ok(error_types: list[str | None], min_types: int) -> bool:
    """Kế hoạch v3, B4: bộ đáp án nhiễu phải phủ ít nhất min_types loại hiểu nhầm khác nhau (không tính None và
    khong_ro), để lựa chọn sai của người học chẩn đoán được nhiều kiểu hiểu nhầm."""
    if min_types <= 0:
        return True
    known = {e for e in error_types if e and e != UNCLEAR}
    return len(known) >= min_types


def _levels(use_form: bool, use_div: bool, ratio: float, conv: bool, use_rank: bool = False
            ) -> dict[str, tuple[float, bool, bool, bool]]:
    """Các mức ràng buộc, thử lần lượt từ chặt tới lỏng: (tỉ lệ độ dài, tránh hội tụ, đa dạng loại lỗi, hạng độ dài).
    Thứ tự ưu tiên: đa dạng loại lỗi (mục tiêu chẩn đoán của v3) > hạng độ dài của key > các ràng buộc hình thức
    khác. Mô phỏng trên kho ứng viên của G1 (93 câu): thứ tự này đưa "key ngắn nhất" từ 41% về 29% mà vẫn giữ
    92,5% bộ đa dạng; đặt hạng độ dài lên trên cả đa dạng thì tỉ lệ bộ đa dạng tụt còn 85%."""
    base = _base_levels(use_form, use_div, ratio, conv)
    out: dict[str, tuple[float, bool, bool, bool]] = {}
    for want_div in (True, False):
        group = {n: v for n, v in base.items() if v[2] == want_div}
        if use_rank:
            out.update({f"{n}+rank": (r, c, d, True) for n, (r, c, d) in group.items()})
            if not want_div:
                out["rank"] = (0, False, False, True)
        out.update({n: (r, c, d, False) for n, (r, c, d) in group.items()})
    return out


def _base_levels(use_form: bool, use_div: bool, ratio: float, conv: bool) -> dict[str, tuple[float, bool, bool]]:
    out: dict[str, tuple[float, bool, bool]] = {}
    if use_div:
        if use_form:
            out["both+diverse"] = (ratio, conv, True)
            out["length+diverse"] = (ratio, False, True)
        out["diverse"] = (0, False, True)
    if use_form:
        out["both"] = (ratio, conv, False)
        out["length"] = (ratio, False, False)
        out["convergence"] = (0, conv, False)
    return out


def select(key_score: float, cand_scores: list[float], mode: str = "entropy", delta: float = 0.15,
           k: int = 3, rng: random.Random | None = None, texts: list[str] | None = None,
           key_text: str | None = None, error_types: list[str | None] | None = None
           ) -> tuple[tuple[int, ...] | None, dict]:
    """Trả (chỉ số k ứng viên được chọn | None, thông tin). Chỉ số tính trên cand_scores.
    mode: entropy (có δ) | entropy_no_delta (đúng như bài gốc) | top3 (k ứng viên đầu) | random.
    texts + key_text: bật ràng buộc hình thức của bộ (chỉ chế độ entropy*).
    error_types (v3): bật ràng buộc đa dạng loại hiểu nhầm (distractor.min_error_types) và trừ điểm phương án
    "khong_ro" (distractor.unclear_penalty, tính theo đơn vị entropy) khi so các bộ."""
    n = len(cand_scores)
    info: dict = {"mode": mode, "delta": delta, "n_candidates": n}
    if n < k:
        info["reason"] = "not_enough_candidates"
        return None, info
    if mode == "top3":
        chosen = tuple(range(k))
    elif mode == "random":
        chosen = tuple(sorted((rng or random.Random()).sample(range(n), k)))
    else:
        cfg = get_config().distractor
        use_form = texts is not None and key_text is not None
        use_div = error_types is not None and cfg.min_error_types > 0
        penalty = cfg.unclear_penalty if error_types is not None else 0.0
        use_rank = use_form and cfg.key_length_rank
        target = feasible_target(key_text, texts, k) if use_rank else None
        levels = _levels(use_form, use_div, cfg.set_length_ratio, cfg.avoid_key_convergence, use_rank)
        best, best_obj, n_ok = None, -math.inf, 0
        best_at = {lv: (None, -math.inf) for lv in levels}
        for S in combinations(range(n), k):
            ev = evaluate_set(key_score, [cand_scores[i] for i in S])
            ok = mode == "entropy_no_delta" or (ev["key_wins"] and ev["margin"] >= delta)
            n_ok += ok
            if not ok:
                continue
            types = [error_types[i] for i in S] if error_types is not None else []
            obj = ev["entropy"] - penalty * sum(t == UNCLEAR for t in types)
            if obj > best_obj:
                best, best_obj = S, obj
            for lv, (r_, c_, d_, k_) in levels.items():
                if obj <= best_at[lv][1]:
                    continue
                if use_form and (r_ or c_) and not form_ok(key_text, [texts[i] for i in S], r_, c_):
                    continue
                if k_ and not rank_ok(key_text, [texts[i] for i in S], target):
                    continue
                if d_ and not diverse_ok(types, cfg.min_error_types):
                    continue
                best_at[lv] = (S, obj)
        info["n_sets"] = math.comb(n, k)
        info["n_sets_ok"] = n_ok
        if best is None:
            info["reason"] = "no_set_satisfies_delta"
            return None, info
        chosen, info["form_level"] = best, "none" if levels else None
        for lv, (S, _) in best_at.items():     # thứ tự chặt → lỏng, xem _levels
            if S is not None:
                chosen, info["form_level"] = S, lv
                break
        if target is not None:
            info["key_len_target"] = target
        if error_types is not None:
            types = [error_types[i] for i in chosen]
            info["error_types"] = types
            info["n_error_types"] = len({t for t in types if t and t != UNCLEAR})
    info.update(evaluate_set(key_score, [cand_scores[i] for i in chosen]))
    return chosen, info


# ---------- Chấm điểm ----------
async def score_reranker(query: str, answer: str, texts: list[str]) -> tuple[float, list[float]]:
    from app.retrieval.reranker import get_reranker

    tau = get_config().distractor.tau
    raw = await asyncio.to_thread(get_reranker().scores, query, [answer, *texts])
    return raw[0] / tau, [s / tau for s in raw[1:]]


async def score_llm(context: str, stem: str, answer: str, texts: list[str]) -> tuple[float, list[float]]:
    """Model giải (judge_independent) chấm tất cả phương án trong MỘT prompt; đọc logprob của nhãn.
    Lặp với vài thứ tự xáo rồi lấy trung bình để triệt thiên lệch vị trí. API không trả logprob thì
    lấy mẫu nhiều lần và đếm tần suất (làm trơn Laplace)."""
    import litellm

    from app.llm_client import _model_for, _reasoning_kwargs

    cfg = get_config()
    options = [answer, *texts]
    acc: list[list[float]] = [[] for _ in options]
    rng = random.Random(len(stem))
    for r in range(max(1, cfg.distractor.llm_score_permutations)):
        order = list(range(len(options)))
        rng.shuffle(order)
        listing = "\n".join(f"{i + 1}. {options[j]}" for i, j in enumerate(order))
        msg = (f"Ngữ cảnh:\n{context}\n\nCâu hỏi: {stem}\n{listing}\n\n"
               f"Chọn phương án đúng nhất. Chỉ trả lời bằng MỘT số từ 1 đến {len(options)}.")
        kw = dict(model=_model_for("judge_independent"), messages=[{"role": "user", "content": msg}],
                  temperature=0, max_tokens=2, timeout=cfg.llm.timeout, **_reasoning_kwargs())
        try:
            resp = await litellm.acompletion(logprobs=True, top_logprobs=20, **kw)
            top = {t.token.strip(): t.logprob for t in resp.choices[0].logprobs.content[0].top_logprobs}
        except Exception as exc:                        # model/API không hỗ trợ logprobs
            log.info("Không lấy được logprobs (%s); chuyển sang đếm tần suất.", exc)
            counts: Counter = Counter()
            for _ in range(8):
                resp = await litellm.acompletion(**{**kw, "temperature": 1.0})
                counts[(resp.choices[0].message.content or "").strip()[:2].strip(".")] += 1
            top = {str(i + 1): math.log((counts[str(i + 1)] + 1) / (8 + len(options))) for i in range(len(options))}
        for i, j in enumerate(order):
            acc[j].append(top.get(str(i + 1), -20.0))
    means = [sum(v) / len(v) for v in acc]
    return means[0], means[1:]


async def score(scorer: str, context: str, evidence: str, stem: str, answer: str,
                texts: list[str]) -> tuple[float, list[float]]:
    if scorer == "llm":
        return await score_llm(context, stem, answer, texts)
    return await score_reranker(f"{evidence}\n{stem}", answer, texts)
