"""Đối chứng "LLM trực tiếp": đưa cho một LLM CÙNG đoạn slide, CÙNG câu hỏi và CÙNG đáp án đúng của V3, chỉ yêu cầu
viết 3 phương án nhiễu bằng MỘT lời gọi (không 7 kiểu hiểu nhầm, không lọc, không xếp hạng, không chọn bộ).
Hai bên chỉ khác nhau ở phương án nhiễu, nên hiệu số đo được là đóng góp của pipeline sinh nhiễu.

  python -m eval.baseline_llm --model openai/gpt-6-luna --name LLM-GPT            # cùng mô hình sinh của V3
  python -m eval.baseline_llm --model gemini/gemini-flash-latest --name LLM-Gemini  # khác họ, gói miễn phí

Ghi eval/quality/data_nlp/<name>_items.jsonl (cùng định dạng export.py). Chạy lại thì tiếp tục từ câu chưa làm.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from eval.quality.common import LETTERS, nfc, read_jsonl, words

PROMPT = """Bạn là giảng viên môn Xử lý ngôn ngữ tự nhiên, đang ra đề trắc nghiệm cho sinh viên từ slide bài giảng.

NỘI DUNG SLIDE:
{context}

CÂU HỎI: {stem}
ĐÁP ÁN ĐÚNG: {key}

Hãy viết đúng 3 phương án SAI (đáp án nhiễu) cho câu hỏi trên. Yêu cầu:
- Chắc chắn sai theo nội dung slide, nhưng nghe hợp lý với sinh viên chưa nắm vững bài (phản ánh những hiểu nhầm thường gặp).
- Cùng chủ đề, cùng dạng câu, văn phong và độ dài tương tự đáp án đúng (khoảng {n} từ), để không thể đoán ra đáp án đúng chỉ nhờ hình thức.
- Ba phương án khác ý nhau, không trùng hay diễn đạt lại đáp án đúng, không dùng "Tất cả đều đúng/sai" hay "Không có đáp án nào".
- Viết bằng tiếng Việt.

Chỉ trả về JSON, không giải thích: {{"distractors": ["...", "...", "..."]}}"""

USAGE = {"calls": 0, "usd": 0.0}


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", nfc(s).lower()).strip()


def parse(text: str, key: str) -> list[str] | None:
    """3 phương án hợp lệ (khác rỗng, khác nhau, khác đáp án đúng) hoặc None."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        ds = json.loads(m.group(0))["distractors"] if m else None
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(ds, list):
        return None
    ds = [d.strip() for d in ds if isinstance(d, str) and d.strip()]
    seen, out = {_norm(key)}, []
    for d in ds:
        if _norm(d) not in seen:
            seen.add(_norm(d))
            out.append(d)
    return out[:3] if len(out) >= 3 else None


def make_item(src: dict, name: str, model: str, ds: list[str], seed: int) -> dict:
    """Câu đối chứng: giữ nguyên chunk, câu hỏi, đáp án đúng của V3; thay 3 phương án nhiễu; trộn thứ tự như export.py."""
    item_id = f"{name.lower()}_{src['chunk_id']}"
    texts = [src["options"][src["key"]], *ds]
    order = list(range(4))
    random.Random(f"{seed}:{item_id}").shuffle(order)
    options = {LETTERS[i]: texts[j] for i, j in enumerate(order)}
    keep = {k: src.get(k) for k in ("chunk_id", "doc_id", "chapter", "slide", "source_context", "concept", "stem",
                                     "bloom_target", "evidence")}
    return {"item_id": item_id, "version": name, **keep, "options": options, "key": LETTERS[order.index(0)],
            "error_types": None, "sources": None, "generator": model}


def _complete(model: str, prompt: str, temperature: float) -> str:
    import litellm

    kw = dict(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature, timeout=90)
    if model.startswith("openai/gpt-6"):
        kw["reasoning_effort"] = "none"          # dòng gpt-6 chỉ nhận temperature ≠ 1 khi tắt reasoning
    try:
        res = litellm.completion(**kw, response_format={"type": "json_object"})
    except Exception as exc:  # noqa: BLE001
        if "429" in str(exc) or "RateLimit" in type(exc).__name__:
            raise
        res = litellm.completion(**kw)
    USAGE["calls"] += 1
    try:
        USAGE["usd"] += float(litellm.completion_cost(completion_response=res) or 0.0)
    except Exception:  # noqa: BLE001
        pass
    return res.choices[0].message.content or ""


def _daily(exc: Exception) -> bool:
    t = str(exc)
    return ("429" in t or "RateLimit" in type(exc).__name__ or "RESOURCE_EXHAUSTED" in t) and (
        "PerDay" in t or "per day" in t.lower() or "daily" in t.lower())


def run(items: list[dict], out: Path, name: str, model: str, *, temperature: float = 0.7, rpm: float | None = None,
        max_usd: float | None = None, seed: int = 42, complete=_complete, sleep=time.sleep) -> dict:
    done = {r["chunk_id"] for r in read_jsonl(out)} if out.exists() else set()
    stat = {"moi": 0, "co_san": len(done), "hong": 0, "dung": None}
    gap = 60.0 / rpm if rpm else 0.0
    for it in items:
        if it["chunk_id"] in done:
            continue
        if max_usd is not None and USAGE["usd"] >= max_usd:
            stat["dung"] = f"chạm trần {max_usd} USD"
            break
        key = it["options"][it["key"]]
        prompt = PROMPT.format(context=it.get("source_context", ""), stem=it["stem"], key=key, n=words(key))
        ds = None
        for attempt in range(3):                       # lần 2, 3: gọi lại khi JSON hỏng hoặc gặp giới hạn theo phút
            if gap:
                sleep(gap)
            try:
                ds = parse(complete(model, prompt, temperature), key)
            except Exception as exc:  # noqa: BLE001
                if _daily(exc):
                    stat["dung"] = "hết hạn mức NGÀY (chạy lại hôm sau, tự tiếp tục)"
                    return stat
                if "429" in str(exc) or "RateLimit" in type(exc).__name__:
                    sleep(65)
                    continue
                print(f"  lỗi {it['item_id']}: {type(exc).__name__}: {str(exc)[:120]}")
            if ds:
                break
        if not ds:
            stat["hong"] += 1
            continue
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(make_item(it, name, model, ds, seed), ensure_ascii=False) + "\n")
        stat["moi"] += 1
        if stat["moi"] % 10 == 0:
            print(f"  {name}: {stat['co_san'] + stat['moi']}/{len(items)} câu, {USAGE['usd']:.3f} USD")
    return stat


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="eval/quality/data_nlp")
    ap.add_argument("--source", default="V3", help="phiên bản lấy chunk, câu hỏi, đáp án đúng")
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", required=True, help="tên phiên bản đối chứng, ví dụ LLM-GPT, LLM-Gemini")
    ap.add_argument("--temperature", type=float, default=0.7, help="bằng temperature_generate của hệ thống")
    ap.add_argument("--rpm", type=float, help="giãn nhịp gọi (gói miễn phí Gemini: 8)")
    ap.add_argument("--max-usd", type=float)
    a = ap.parse_args()
    data = Path(a.data)
    items = read_jsonl(data / f"{a.source}_items.jsonl")
    out = data / f"{a.name}_items.jsonl"
    print(f"Sinh đối chứng {a.name} bằng {a.model} cho {len(items)} câu của {a.source}...")
    st = run(items, out, a.name, a.model, temperature=a.temperature, rpm=a.rpm, max_usd=a.max_usd)
    n = len(read_jsonl(out)) if out.exists() else 0
    print(f"{a.name}: {n}/{len(items)} câu (mới {st['moi']}, hỏng {st['hong']}); "
          f"{USAGE['calls']} lần gọi, {USAGE['usd']:.4f} USD.")
    if st["dung"]:
        print(f"  ⚠ Dừng sớm: {st['dung']}")
        raise SystemExit(3)


if __name__ == "__main__":
    main()
