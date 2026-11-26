"""Bước 2: thống kê tự động trên snapshot. Không gọi API, không cần người chấm.
Chạy: python -m eval.mcq.step2_stats   → in ra màn hình và ghi results/thong_ke.csv
"""
from collections import Counter, defaultdict

from scipy.stats import chisquare

from app.generation.common import LETTERS
from eval.mcq.common import RESULTS_DIR, load_chunks, load_meta, load_questions, rule_of, wilson, write_csv


def build_stats(questions: list[dict], chunks: dict[int, dict], meta: dict) -> list[dict]:
    rows: list[dict] = []

    def add(group: str, name: str, value: float | int | str, note: str = "") -> None:
        rows.append({"nhom": group, "chi_so": name, "gia_tri": round(value, 3) if isinstance(value, float) else value,
                     "ghi_chu": note})

    def rate(group: str, name: str, subset: list[dict]) -> None:
        n, ok = len(subset), sum(q["status"] == "accepted" for q in subset)
        low, high = wilson(ok, n)
        add(group, name, ok / n if n else 0.0, f"{ok}/{n}, KTC 95%: {low:.2f}–{high:.2f}")

    accepted = [q for q in questions if q["status"] == "accepted"]
    documents = {d["id"]: d for d in meta["documents"]}

    rate("ti_le_accepted", "tong", questions)
    for doc_id, doc in documents.items():
        rate("ti_le_accepted", doc["filename"], [q for q in questions if q["document_id"] == doc_id])
    for level in meta["bank"]["bloom_mix"]:
        rate("ti_le_accepted", level, [q for q in questions if q["bloom_level"] == level])

    rejected = [q for q in questions if q["status"] == "rejected"]
    for rule, count in Counter(rule_of(q["validation"]) or "khong_ro" for q in rejected).most_common():
        add("pheu_loai", rule, count, f"{count}/{len(rejected)} câu bị loại")

    by_attempt: dict[int, list[dict]] = defaultdict(list)
    for q in questions:
        by_attempt[q["validation"].get("attempt", 0)].append(q)
    for attempt in sorted(by_attempt):
        rate("dat_theo_lan_thu", f"lan_{attempt}", by_attempt[attempt])

    per_slide = meta["bank"]["questions_per_slide"]
    for doc_id, doc in documents.items():
        target = max(1, round(doc["num_slides"] * per_slide))
        got = sum(q["document_id"] == doc_id for q in accepted)
        add("dat_muc_tieu", doc["filename"], got / target, f"{got}/{target} câu, {doc['num_slides']} slide")

    eligible = {i for i, c in chunks.items() if c["words"] >= meta["bank"]["min_seed_words"]}
    covered = {i for q in accepted for i in q["source_chunk_ids"]} & eligible
    add("do_phu_slide", "chunk_du_dieu_kien_co_cau_hoi", len(covered) / len(eligible) if eligible else 0.0,
        f"{len(covered)}/{len(eligible)} chunk từ {meta['bank']['min_seed_words']} từ trở lên")

    bloom_counts = Counter(q["bloom_level"] for q in accepted)
    for level, share in meta["bank"]["bloom_mix"].items():
        add("phan_bo_bloom", level, bloom_counts[level] / len(accepted) if accepted else 0.0, f"cấu hình: {share}")
    differ = sum(q["validation"].get("llm_bloom_level") != q["bloom_level"] for q in accepted)
    add("phan_bo_bloom", "llm_tu_ghi_khac_muc_yeu_cau", differ, f"{differ}/{len(accepted)} câu")

    answer_counts = [sum(q["answer"] == letter for q in accepted) for letter in LETTERS]
    for letter, count in zip(LETTERS, answer_counts, strict=True):
        add("vi_tri_dap_an", letter, count / len(accepted) if accepted else 0.0, "kỳ vọng 0.25")
    if accepted:
        p_value = float(chisquare(answer_counts).pvalue)
        add("vi_tri_dap_an", "chi_binh_phuong_p", p_value, "p > 0.05: chưa thấy dấu hiệu lệch")

    dup = meta["duplicates"]
    add("trung_lap", "cap_vuot_nguong", dup["pairs"] and dup["over_threshold"] / dup["pairs"],
        f"{dup['over_threshold']}/{dup['pairs']} cặp cùng tài liệu > {dup['threshold']}")
    add("trung_lap", "cosine_cao_nhat", float(dup["max_similarity"]))
    return rows


def main() -> None:
    questions, chunks, meta = load_questions(), load_chunks(), load_meta()
    rows = build_stats(questions, chunks, meta)
    group = None
    for row in rows:
        if row["nhom"] != group:
            group = row["nhom"]
            print(f"\n[{group}]")
        print(f"  {row['chi_so']}: {row['gia_tri']}  {row['ghi_chu']}")
    path = RESULTS_DIR / "thong_ke.csv"
    write_csv(path, rows)
    print(f"\nĐã ghi: {path}")


if __name__ == "__main__":
    main()
