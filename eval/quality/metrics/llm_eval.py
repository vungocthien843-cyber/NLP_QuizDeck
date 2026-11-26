"""Lớp S (solver) và J (LLM judge) của bộ đánh giá chất lượng (kế hoạch v3, việc A6). Prompt P1–P8 ở prompts/.

Mô hình lấy từ config.yaml → eval_models (phải KHÁC HỌ với mô hình sinh câu hỏi), gọi qua LiteLLM nên dùng được mọi
nhà cung cấp LiteLLM hỗ trợ ("<provider>/<model>"); API key đặt trong .env như thường lệ.

Lớp S, mỗi solver × mỗi điều kiện × eval_llm.runs lần, mỗi lần xáo lại thứ tự phương án:
  S8_open_book    P8 có ngữ cảnh chọn đúng       → gần 100%; thấp = câu sai hoặc mơ hồ
  S7_closed_book  P7 không ngữ cảnh chọn đúng    → càng thấp đáp án nhiễu càng đánh lừa tốt
  S6_options_only P6 chỉ xem phương án chọn đúng  → gần 25%; cao = đáp án đúng lộ qua hình thức
Giá trị của một câu = tỉ lệ đúng trên mọi solver và mọi lần chạy (lần lỗi/không đọc được bỏ qua).

Lớp J, judge chạy một lần mỗi câu (temperature 0):
  J1_key_supported     P1: ngữ cảnh hỗ trợ đáp án đúng (yes 1, partial 0,5, no 0)
  J2_unique_correct    P2: đúng key là phương án đúng duy nhất, mọi phương án khác là sai
  J2_multi_correct     P2: có từ 2 phương án được chấm là đúng
  J3_stem_standalone   P3: chỉ xem câu hỏi + ngữ cảnh, câu trả lời tự do chứa ≥ 50% âm tiết nội dung của key
  J4_usable            P4: dùng được ngay (yes 1, minor_edit 0,5, no 0)
  J4_distractor_flaw   P4: có ít nhất một lỗi nhóm D (đáp án nhiễu)
  J5_bloom_match       P5: mức Bloom judge chấm trùng mức yêu cầu (bloom_target)

Kết quả gọi mô hình được lưu đệm ở eval/quality/cache/llm_cache.jsonl theo (mô hình, prompt, câu, lần chạy, thứ tự
phương án), nên chạy lại báo cáo không tốn thêm API. Xoá file đệm để chấm lại.
"""
import asyncio
import hashlib
import json
import random
import re
from pathlib import Path

from eval.quality.common import LETTERS, ROOT, content_tokens

PROMPTS = ROOT / "prompts"
CACHE = ROOT / "cache" / "llm_cache.jsonl"
_PROMPT_FILES = {
    "P1": "P1_bam_nguon.txt", "P2": "P2_dung_duy_nhat.txt", "P3": "P3_stem_tu_dung.txt",
    "P4": "P4_loi_soan_cau.txt", "P5": "P5_bloom.txt", "P6": "P6_solver_options_only.txt",
    "P7": "P7_solver_no_context.txt", "P8": "P8_solver_with_context.txt",
}
SOLVER_PROMPTS = {"S8_open_book": "P8", "S7_closed_book": "P7", "S6_options_only": "P6"}

S_COLUMNS = {
    "S8_open_book": ("Solver có ngữ cảnh chọn đúng (P8)", "S", "≈ 1,0"),
    "S7_closed_book": ("Solver không ngữ cảnh chọn đúng (P7)", "S", "thấp"),
    "S6_options_only": ("Solver chỉ xem phương án chọn đúng (P6)", "S", "≈ 0,25"),
}
J_COLUMNS = {
    "J1_key_supported": ("Ngữ cảnh hỗ trợ đáp án đúng (P1)", "K1", "≈ 1,0"),
    "J2_unique_correct": ("Key là phương án đúng duy nhất (P2)", "K2", "≈ 1,0"),
    "J2_multi_correct": ("Có ≥ 2 phương án đúng (P2)", "K2", "0"),
    "J3_stem_standalone": ("Câu hỏi tự trả lời được khi không có phương án (P3)", "S1", "cao"),
    "J4_usable": ("Dùng được ngay (P4)", "—", "cao"),
    "J4_distractor_flaw": ("Có lỗi đáp án nhiễu nhóm D (P4)", "D", "thấp"),
    "J5_bloom_match": ("Đúng mức Bloom yêu cầu (P5)", "C2", "cao"),
}


def _prompt(name: str) -> str:
    return (PROMPTS / _PROMPT_FILES[name]).read_text(encoding="utf-8")


def render(name: str, item: dict, options: dict[str, str]) -> str:
    """Thay {biến} trong prompt. Không dùng str.format vì prompt có sẵn dấu ngoặc nhọn của JSON mẫu."""
    values = {"source_context": item.get("source_context") or "", "stem": item["stem"],
              "key_text": item["options"][item["key"]], "key": item["key"], **options}
    text = _prompt(name)
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def parse_json(text: str) -> dict:
    """Đọc object JSON đầu tiên trong câu trả lời (mô hình có thể bọc trong ```json ... ```)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                pass
    return {}


def shuffled(item: dict, rng: random.Random) -> tuple[dict[str, str], str]:
    """Xáo phương án; trả (phương án theo chữ cái mới, chữ cái mới của key)."""
    letters = list(LETTERS)
    order = letters[:]
    rng.shuffle(order)
    opts = {new: item["options"][old] for new, old in zip(letters, order)}
    return opts, letters[order.index(item["key"])]


# ---------- Gọi mô hình (có lưu đệm) ----------
def _is_daily_quota(exc: Exception) -> bool:
    """Lỗi 429 vì hết hạn mức NGÀY (gói miễn phí Gemini: ...PerDay...) → chờ không có ích, dừng gọi model đó."""
    t = str(exc)
    return "PerDay" in t or "per day" in t.lower() or "daily" in t.lower()


def _is_rate_limit(exc: Exception) -> bool:
    t = f"{type(exc).__name__} {exc}"
    return "RateLimit" in t or "429" in t or "RESOURCE_EXHAUSTED" in t


class Caller:
    def __init__(self, temperature: float, concurrency: int, complete=None, use_cache: bool = True,
                 rpm: dict[str, float] | None = None, retries: int = 4, wait: float = 65.0):
        self.temperature = temperature
        self.sem = asyncio.Semaphore(concurrency)
        self._complete = complete or _litellm_complete
        self.use_cache = use_cache
        self.cache: dict[str, str] = {}
        self.calls = 0
        self.errors: dict[str, int] = {}
        # Gói miễn phí (G1, 15/11: ~4.500 lỗi 429): giãn nhịp gọi theo rpm của từng model, 429 theo phút thì chờ rồi
        # thử lại, 429 theo ngày thì đánh dấu model "hết hạn mức" và bỏ qua mọi lần gọi còn lại (chạy lại hôm sau).
        self.rpm = rpm or {}
        self.retries, self.wait = retries, wait
        self._next_slot: dict[str, float] = {}
        self._slot_lock: dict[str, asyncio.Lock] = {}
        self.exhausted: set[str] = set()
        self.skipped = 0
        self.max_usd: float | None = None          # trần chi phí cho lần chạy (eval_llm.max_usd / --max-usd)
        self.budget_hit = False
        if use_cache and CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.cache[r["k"]] = r["text"]

    def _over_budget(self) -> bool:
        if self.max_usd is not None and USAGE["usd"] >= self.max_usd:
            if not self.budget_hit:
                print(f"  ⚠ Đã chạm trần chi phí {self.max_usd:.2f} USD: dừng gọi mô hình, phần đã chấm được giữ.")
            self.budget_hit = True
            return True
        return False

    async def __call__(self, model: str, prompt: str, tag: str) -> str | None:
        k = hashlib.sha1(f"{model}\x00{self.temperature}\x00{prompt}\x00{tag}".encode()).hexdigest()
        if k in self.cache:
            return self.cache[k]
        if model in self.exhausted or self._over_budget():
            self.skipped += 1
            return None
        async with self.sem:
            text = None
            for attempt in range(self.retries + 1):
                if model in self.exhausted:
                    self.skipped += 1
                    return None
                await self._pace(model)
                try:
                    text = await self._complete(model, prompt, self.temperature)
                    break
                except Exception as exc:  # noqa: BLE001
                    if _is_rate_limit(exc) and _is_daily_quota(exc):
                        if model not in self.exhausted:
                            print(f"  ⚠ {model}: hết hạn mức NGÀY, dừng gọi model này (chạy lại hôm sau).")
                        self.exhausted.add(model)
                        self.skipped += 1
                        return None
                    if _is_rate_limit(exc) and attempt < self.retries:
                        await asyncio.sleep(self.wait)
                        continue
                    name = f"{model}: {type(exc).__name__}"
                    self.errors[name] = self.errors.get(name, 0) + 1
                    return None
        self.calls += 1
        self.cache[k] = text
        if self.use_cache:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            with CACHE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"k": k, "model": model, "text": text}, ensure_ascii=False) + "\n")
        return text


async def _pace_impl(self, model: str) -> None:
    rpm = next((v for k, v in self.rpm.items() if k in model), None)
    if not rpm:
        return
    import time
    lock = self._slot_lock.setdefault(model, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        at = max(now, self._next_slot.get(model, 0.0))
        self._next_slot[model] = at + 60.0 / rpm
    if at > now:
        await asyncio.sleep(at - now)


Caller._pace = _pace_impl


# Chi phí THẬT của các lần gọi mới (không tính lần lấy từ bộ đệm): cộng dồn trong một lần chạy run_eval
USAGE: dict = {"calls": 0, "in": 0, "out": 0, "usd": 0.0, "usd_known": True, "by_model": {}}


def _reasoning_kwargs(model: str) -> dict:
    """Dòng gpt-6 chỉ nhận temperature ≠ 1 khi tắt reasoning (giống app/llm_client.py)."""
    if not model.startswith("openai/gpt-6"):
        return {}
    try:
        from app.config import get_config
        effort = get_config().llm.reasoning_effort
    except Exception:  # noqa: BLE001  chạy ngoài app
        effort = "none"
    return {"reasoning_effort": effort} if effort else {}


def _track(model: str, res) -> None:
    import litellm

    u = getattr(res, "usage", None)
    pin, pout = (getattr(u, "prompt_tokens", 0) or 0), (getattr(u, "completion_tokens", 0) or 0)
    try:
        usd = float(litellm.completion_cost(completion_response=res) or 0.0)
    except Exception:  # noqa: BLE001  model chưa có bảng giá trong LiteLLM
        usd = 0.0
    if usd == 0.0 and (pin or pout):
        USAGE["usd_known"] = False
    m = USAGE["by_model"].setdefault(model, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
    for d in (USAGE, m):
        d["calls"] += 1
        d["in"] += pin
        d["out"] += pout
        d["usd"] += usd


async def _litellm_complete(model: str, prompt: str, temperature: float) -> str:
    import litellm

    kwargs = dict(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature, timeout=90,
                  **_reasoning_kwargs(model))
    try:
        res = await litellm.acompletion(**kwargs, response_format={"type": "json_object"})
    except Exception as exc:  # noqa: BLE001  một số nhà cung cấp không nhận response_format: gọi lại không có nó
        if "RateLimit" in type(exc).__name__ or "429" in str(exc):
            raise
        res = await litellm.acompletion(**kwargs)
    _track(model, res)
    return res.choices[0].message.content or ""


# ---------- Lớp S ----------
async def solver_item(call: Caller, item: dict, solvers: list[str], runs: int, seed: int) -> dict:
    out = {}
    for col, pname in SOLVER_PROMPTS.items():
        tasks = []
        for model in solvers:
            for r in range(runs):
                rng = random.Random(f"{seed}:{item['item_id']}:{pname}:{r}")
                opts, key_letter = shuffled(item, rng)
                tag = f"{pname}:{item['item_id']}:{r}:{''.join(opts[x][:8] for x in LETTERS)}"
                tasks.append((call(model, render(pname, item, opts), tag), key_letter))
        texts = await asyncio.gather(*(t for t, _ in tasks))
        hits = []
        for text, (_, key_letter) in zip(texts, tasks, strict=True):
            if text is None:                       # gọi lỗi: bỏ qua, KHÔNG tính là trả lời sai
                continue
            ans = str(parse_json(text).get("answer", "")).strip().upper()[:1]
            if ans and ans in LETTERS:             # "" in "ABCD" là True trong Python, phải loại riêng
                hits.append(float(ans == key_letter))
        out[col] = sum(hits) / len(hits) if hits else None
    return out


# ---------- Lớp J ----------
def _p3_hit(answer: str, key: str) -> float | None:
    k = set(content_tokens(key))
    if not k:
        return None
    a = set(content_tokens(answer))
    return float(len(k & a) / len(k) >= 0.5)


async def judge_item(call: Caller, item: dict, judge: str, prompts: tuple = ("P1", "P2", "P3", "P4", "P5")) -> dict:
    opts = {x: item["options"][x] for x in LETTERS}
    names = tuple(p for p in ("P1", "P2", "P3", "P4", "P5") if p in prompts)   # tiết kiệm: chỉ chạy prompt cần
    texts = await asyncio.gather(*(call(judge, render(p, item, opts), f"{p}:{item['item_id']}") for p in names))
    j = {p: None for p in ("P1", "P2", "P3", "P4", "P5")}
    j.update({p: parse_json(t or "") if t is not None else None for p, t in zip(names, texts, strict=True)})
    out: dict = {c: None for c in J_COLUMNS}
    if j["P1"]:
        out["J1_key_supported"] = {"yes": 1.0, "partial": 0.5, "no": 0.0}.get(str(j["P1"].get("supported")).lower())
    if j["P2"]:
        verdicts = {x: str(j["P2"].get(x, "")).lower() for x in LETTERS}
        if all(v in ("correct", "incorrect", "undetermined") for v in verdicts.values()):
            n_correct = sum(v == "correct" for v in verdicts.values())
            out["J2_unique_correct"] = float(verdicts[item["key"]] == "correct" and n_correct == 1
                                             and all(v == "incorrect" for x, v in verdicts.items() if x != item["key"]))
            out["J2_multi_correct"] = float(n_correct >= 2)
    if j["P3"]:
        out["J3_stem_standalone"] = _p3_hit(str(j["P3"].get("answer", "")), item["options"][item["key"]])
    if j["P4"]:
        out["J4_usable"] = {"yes": 1.0, "minor_edit": 0.5, "no": 0.0}.get(str(j["P4"].get("overall_usable")).lower())
        flaws = j["P4"].get("flaws") or []
        if isinstance(flaws, list):
            out["J4_distractor_flaw"] = float(any(str((f or {}).get("code", "")).upper().startswith("D")
                                                  for f in flaws if isinstance(f, dict)))
    if j["P5"] and item.get("bloom_target"):
        out["J5_bloom_match"] = float(str(j["P5"].get("bloom", "")).lower() == item["bloom_target"])
    return out


# ---------- Ghép vào run_eval ----------
def check_models(cfg: dict, layers: list[str]) -> tuple[str | None, list[str]]:
    em = cfg.get("eval_models") or {}
    judge, solvers = em.get("judge"), list(em.get("solvers") or [])
    gens = set(cfg.get("generator_models") or [])
    if "J" in layers and not judge:
        raise SystemExit("Lớp J cần eval_models.judge trong eval/quality/config.yaml (mô hình khác họ với mô hình sinh).")
    if "S" in layers and not solvers:
        raise SystemExit("Lớp S cần ít nhất 1 mô hình trong eval_models.solvers (eval/quality/config.yaml).")
    clash = gens & ({judge} | set(solvers))
    if clash:
        print(f"CẢNH BÁO: mô hình đánh giá trùng mô hình sinh: {sorted(clash)} — kết quả J/S thiên vị, ghi vào hạn chế.")
    return judge, solvers


async def run_layers(per_version: dict, items: dict, layers: list[str], cfg: dict, complete=None) -> dict:
    """Thêm cột S*/J* vào các dòng per_item của mọi phiên bản. Trả thống kê lần chạy (số lần gọi, lỗi)."""
    judge, solvers = check_models(cfg, layers)
    lc = cfg.get("eval_llm") or {}
    call = Caller(lc.get("temperature", 0.0), lc.get("concurrency", 5), complete, lc.get("cache", True),
                  rpm=lc.get("rpm"), retries=lc.get("retries", 4), wait=lc.get("retry_wait", 65.0))
    call.max_usd = lc.get("max_usd")
    runs, seed = lc.get("runs", 2), cfg.get("seed", 42)
    for v, rows in per_version.items():
        by_id = {it["item_id"]: it for it in items[v]}

        async def one(row: dict) -> None:
            it = by_id[row["item_id"]]
            if "S" in layers:
                row.update(await solver_item(call, it, solvers, runs, seed))
            if "J" in layers:
                row.update(await judge_item(call, it, judge, tuple(lc.get("judge_prompts") or
                                                                   ("P1", "P2", "P3", "P4", "P5"))))
        await asyncio.gather(*(one(r) for r in rows))
        print(f"  {v}: xong lớp {'/'.join(x for x in layers if x in 'SJ')} ({call.calls} lần gọi mới tới giờ)")
    return {"judge": judge, "solvers": solvers, "runs": runs, "new_calls": call.calls, "errors": call.errors,
            "quota_exhausted": sorted(call.exhausted), "skipped_calls": call.skipped, "budget_hit": call.budget_hit,
            "usage": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in USAGE.items()}}
