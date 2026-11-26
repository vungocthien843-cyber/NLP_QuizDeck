"""Phân tích thử nghiệm sinh viên (Mốc 3, G4 + G5). Đọc thẳng từ DB, chạy trong container API.

G4  Phân tích câu hỏi theo lý thuyết trắc nghiệm cổ điển trên Đề 1 và Đề 2:
      p (tỉ lệ đúng), D (nhóm 27% điểm cao − nhóm 27% thấp), r_pb (tương quan điểm-nhị phân với điểm phần còn lại),
      tỉ lệ chọn từng phương án sai, phương án sai "không hoạt động" (< 5% chọn).
    So sánh V1 và V3 theo CẶP CÙNG SLIDE (mỗi slide có một câu V1 ở đề này và một câu V3 ở đề kia).
    Tỉ lệ đúng theo mức khó ước lượng (phải giảm dần dễ → khó). Phản hồi của sinh viên về chẩn đoán và lời giải thích.
G5  Vòng cá nhân hoá: nhóm A (luyện điểm yếu) và nhóm B (luyện đề thường) — điểm Đề 2 − Đề 1, tỉ lệ sửa được
    các slide đã sai ở Đề 1, tỉ lệ lặp lại đúng loại hiểu nhầm cũ. Mẫu nhỏ: chỉ báo cáo mô tả kèm CI, không kết luận
    nhân quả.
Kết quả: eval/student/results/bao_cao_sinh_vien.md + phan_tich_cau.csv + theo_sinh_vien.csv
  python -m eval.student.phan_tich [--config eval/student/data/thu_nghiem_dong_....json]
"""
import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from eval.student.common import RESULTS, write_csv

BOOT = 10000
NFD = 0.05            # phương án sai được chọn < 5% → "không hoạt động"
LEVEL_ORDER = {"easy": 0, "medium": 1, "hard": 2}
LEVEL_VI = {"easy": "Dễ", "medium": "Trung bình", "hard": "Khó"}
DIAG_VI = {2: "Đúng", 1: "Một phần", 0: "Không đúng"}
G4_SUMMARY: list[dict] = []          # các số chính của G4 → g4_tong_hop.csv (báo cáo tổng hợp đọc file này)


# ----------------------------------------------------------------------------- thống kê
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def boot_ci(values: list[float], rng: random.Random) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    n = len(values)
    b = sorted(mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(BOOT))
    return b[int(0.025 * BOOT)], b[int(0.975 * BOOT) - 1]


def boot_diff(a: list[float], b: list[float], rng: random.Random) -> tuple[float, float]:
    """CI của mean(b) − mean(a), hai mẫu độc lập."""
    if len(a) < 2 or len(b) < 2:
        return (float("nan"), float("nan"))
    d = sorted(mean(b[rng.randrange(len(b))] for _ in b) - mean(a[rng.randrange(len(a))] for _ in a)
               for _ in range(BOOT))
    return d[int(0.025 * BOOT)], d[int(0.975 * BOOT) - 1]


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy)


def fmt(v, d: int = 3) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"


# ----------------------------------------------------------------------------- phân tích câu (CTT)
def item_analysis(resp: list[dict], items: dict[int, dict]) -> list[dict]:
    """resp: {user, question_id, chosen, correct} của MỘT đề (mỗi người làm một lần). items: question_id → thông tin."""
    by_user = defaultdict(dict)
    for r in resp:
        by_user[r["user"]][r["question_id"]] = r
    totals = {u: sum(x["correct"] for x in rs.values()) for u, rs in by_user.items()}
    ranked = sorted(totals, key=lambda u: totals[u])
    k = max(1, math.ceil(0.27 * len(ranked)))
    lower, upper = set(ranked[:k]), set(ranked[-k:])
    out = []
    for qid, info in items.items():
        rs = [by_user[u][qid] for u in by_user if qid in by_user[u]]
        if not rs:
            continue
        n = len(rs)
        p = mean(float(r["correct"]) for r in rs)
        up = [r["correct"] for r in rs if r["user"] in upper]
        lo = [r["correct"] for r in rs if r["user"] in lower]
        d = (mean(up) - mean(lo)) if up and lo else None
        rest = [totals[r["user"]] - r["correct"] for r in rs]
        rpb = pearson([float(r["correct"]) for r in rs], [float(x) for x in rest])
        chosen = Counter(r["chosen"] for r in rs)
        dis = [L for L, m in info["option_meta"].items() if m.get("role") == "distractor"]
        dist = {L: chosen.get(L, 0) / n for L in dis}
        out.append({"question_id": qid, "de": info["de"], "phien_ban": info["version"], "slide": info["slide"],
                    "muc_kho": info.get("level"), "n": n, "p": round(p, 4),
                    "D": None if d is None else round(d, 4), "r_pb": None if rpb is None else round(rpb, 4),
                    "pa_khong_hoat_dong": sum(v < NFD for v in dist.values()),
                    "ty_le_chon": json.dumps({L: round(v, 3) for L, v in dist.items()}),
                    "loai_loi": json.dumps({L: info["option_meta"][L].get("error_type") for L in dis},
                                           ensure_ascii=False)})
    return out


def paired_by_slide(rows: list[dict], key: str, rng: random.Random) -> dict | None:
    by_slide = defaultdict(dict)
    for r in rows:
        if r[key] is not None:
            by_slide[r["slide"]][r["phien_ban"]] = r[key]
    pairs = [(v["V1"], v["V3"]) for v in by_slide.values() if "V1" in v and "V3" in v]
    if len(pairs) < 2:
        return None
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    d = [y - x for x, y in pairs]
    lo, hi = boot_ci(d, rng)
    p = None
    if any(d) and len(pairs) >= 5:
        from scipy.stats import wilcoxon
        p = float(wilcoxon(d, zero_method="wilcox").pvalue)
    return {"n": len(pairs), "V1": mean(a), "V3": mean(b), "hieu": mean(d), "lo": lo, "hi": hi, "p": p}


# ----------------------------------------------------------------------------- nạp dữ liệu
def load(cfg: dict) -> dict:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Attempt, Feedback, Question, Quiz, QuizQuestion, Response, User

    with SessionLocal() as db:
        users = {u.id: u for u in db.scalars(select(User).where(User.code.in_(list(cfg["members"]))))}
        group = {uid: cfg["members"][u.code] for uid, u in users.items()}
        fixed = {cfg["quiz1_id"]: 1, cfg["quiz2_id"]: 2}
        items = {}
        for qq, q in db.execute(select(QuizQuestion, Question).join(Question, Question.id == QuizQuestion.question_id)
                                .where(QuizQuestion.quiz_id.in_(list(fixed)))):
            exp = (q.validation or {}).get("experiment") or {}
            items[q.id] = {"de": fixed[qq.quiz_id], "version": exp.get("version"), "slide": exp.get("seed_chunk")
                           or q.source_chunk_ids[0], "level": q.difficulty_est, "option_meta": q.option_meta or {}}
        atts = list(db.scalars(select(Attempt).where(Attempt.user_id.in_(list(users))).order_by(Attempt.submitted_at)))
        quizzes = {z.id: z for z in db.scalars(select(Quiz).where(Quiz.id.in_({a.quiz_id for a in atts} or {-1})))}
        first = {}                                     # (user, đề) → lần làm đầu tiên
        practice = {}
        for a in atts:
            if a.quiz_id in fixed:
                first.setdefault((a.user_id, fixed[a.quiz_id]), a)
            elif (quizzes[a.quiz_id].scope or {}).get("practice"):
                practice.setdefault(a.user_id, a)
        keep = {a.id: (u, k) for (u, k), a in first.items()}
        resp = defaultdict(list)
        for r in db.scalars(select(Response).where(Response.attempt_id.in_(list(keep) or [-1]))):
            u, k = keep[r.attempt_id]
            resp[k].append({"user": u, "question_id": r.question_id, "chosen": r.chosen, "correct": int(r.is_correct),
                            "error_type": r.error_type})
        pr_info = {}
        for u, a in practice.items():
            z = quizzes[a.quiz_id]
            n_targeted = sum(1 for qq in db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == z.id)) if qq.reason)
            pr_info[u] = {"mode": z.mode, "targeted": n_targeted, "n": z.num_questions, "score": a.score}
        fb = [{"user": f.user_id, "attempt": f.attempt_id, "question_id": f.question_id, "kind": f.kind,
               "value": f.value, "comment": f.comment}
              for f in db.scalars(select(Feedback).where(Feedback.user_id.in_(list(users) or [-1])))]
        att_quiz = {a.id: fixed.get(a.quiz_id, 0) for a in atts}
    return {"users": {uid: u.code for uid, u in users.items()}, "group": group, "items": items, "resp": dict(resp),
            "scores": {(u, k): a.score for (u, k), a in first.items()}, "practice": pr_info, "feedback": fb,
            "att_quiz": att_quiz}


# ----------------------------------------------------------------------------- báo cáo
def g4(data: dict, rng: random.Random, md: list[str]) -> list[dict]:
    rows = []
    for k in (1, 2):
        its = {q: i for q, i in data["items"].items() if i["de"] == k}
        rows += item_analysis(data["resp"].get(k, []), its)
    n1 = len({r["user"] for r in data["resp"].get(1, [])})
    n2 = len({r["user"] for r in data["resp"].get(2, [])})
    md.append(f"## G4: chất lượng câu hỏi qua bài làm thật\n\nĐề 1: {n1} sinh viên · Đề 2: {n2} sinh viên.\n")
    if not rows:
        md.append("_Chưa có bài làm._\n")
        return rows
    md.append("### V1 và V3 theo cặp cùng slide\n")
    md.append("Hiệu = V3 − V1, khoảng tin cậy 95% bootstrap theo cặp; p theo Wilcoxon (chỉ khi ≥ 5 cặp). "
              "D và r_pb càng cao càng phân biệt tốt người nắm bài và người chưa nắm; số phương án sai không hoạt "
              f"động (< {NFD:.0%} chọn) càng thấp càng tốt.\n")
    md.append("| Chỉ số | Số cặp | V1 | V3 | Hiệu | CI 95% | p |\n|---|---|---|---|---|---|---|")
    for key, label in (("p", "Tỉ lệ đúng p"), ("D", "Độ phân biệt D"), ("r_pb", "Tương quan r_pb"),
                       ("pa_khong_hoat_dong", "Số PA sai không hoạt động / câu")):
        res = paired_by_slide(rows, key, rng)
        if res:
            G4_SUMMARY.append({"chi_so": key, "ten": label, **res})
            md.append(f"| {label} | {res['n']} | {fmt(res['V1'])} | {fmt(res['V3'])} | {res['hieu']:+.3f} | "
                      f"[{fmt(res['lo'])}; {fmt(res['hi'])}] | {fmt(res['p'], 4)} |")
    nfd = {v: [r["pa_khong_hoat_dong"] for r in rows if r["phien_ban"] == v] for v in ("V1", "V3")}
    for v, xs in nfd.items():
        if xs:
            G4_SUMMARY.append({"chi_so": f"NFD%_{v}", "ten": f"Tỉ lệ phương án nhiễu không hoạt động ({v})",
                               v: sum(xs) / (3 * len(xs)), "n": len(xs)})
            md.append(f"\n- {v}: {sum(xs)}/{3 * len(xs)} phương án sai không hoạt động "
                      f"({sum(xs) / (3 * len(xs)):.0%}); {sum(r['D'] is not None and r['D'] < 0.1 for r in rows if r['phien_ban'] == v)}"
                      f"/{len(xs)} câu có D < 0,1.")

    md.append("\n### Tỉ lệ đúng theo mức khó ước lượng (kỳ vọng giảm dần Dễ → Khó)\n")
    md.append("| Mức | Số câu | Lượt trả lời | Tỉ lệ đúng | CI 95% Wilson |\n|---|---|---|---|---|")
    pooled = defaultdict(lambda: [0, 0, 0])
    for k, rs in data["resp"].items():
        for r in rs:
            lv = data["items"][r["question_id"]]["level"]
            pooled[lv][0] += r["correct"]
            pooled[lv][1] += 1
    for r in rows:
        pooled[r["muc_kho"]][2] += 1
    for lv in sorted(pooled, key=lambda x: LEVEL_ORDER.get(x, 9)):
        c, n, ni = pooled[lv]
        lo, hi = wilson(c, n)
        md.append(f"| {LEVEL_VI.get(lv, lv)} | {ni} | {n} | {c / n:.0%} | [{lo:.0%}; {hi:.0%}] |")
    lv_rows = [r for r in rows if r["muc_kho"] in LEVEL_ORDER]
    if len(lv_rows) >= 5:
        from scipy.stats import spearmanr
        rho, p = spearmanr([LEVEL_ORDER[r["muc_kho"]] for r in lv_rows], [r["p"] for r in lv_rows])
        md.append(f"\nSpearman giữa mức khó ước lượng (0 dễ … 2 khó) và tỉ lệ đúng của từng câu: ρ = {fmt(float(rho))} "
                  f"(p = {fmt(float(p), 4)}). Âm nghĩa là ước lượng đúng chiều.\n")

    # chẩn đoán có được gắn không, sinh viên thấy có đúng không
    md.append("### Chẩn đoán hiểu nhầm\n")
    wrong = [(r, data["items"][r["question_id"]]["version"]) for rs in data["resp"].values() for r in rs if not r["correct"]]
    for v in ("V1", "V3"):
        w = [r for r, ver in wrong if ver == v]
        if w:
            lab = sum(1 for r in w if r["error_type"] and r["error_type"] != "khong_ro")
            md.append(f"- Câu {v}: {lab}/{len(w)} lần chọn sai có chẩn đoán cụ thể ({lab / len(w):.0%}).")
    di = [f for f in data["feedback"] if f["kind"] == "diag_item"]
    if di:
        vers = {f["question_id"]: data["items"].get(f["question_id"], {}).get("version") for f in di}
        md.append("\nSinh viên đánh giá chẩn đoán từng câu (“chẩn đoán có đúng với điều bạn đã nghĩ khi chọn?”):\n")
        md.append("| Phiên bản | Đúng | Một phần | Không đúng | n |\n|---|---|---|---|---|")
        for v in ("V1", "V3", None):
            xs = [f["value"] for f in di if v is None or vers[f["question_id"]] == v]
            if xs:
                c = Counter(xs)
                md.append(f"| {v or 'Tất cả'} | {c[2] / len(xs):.0%} | {c[1] / len(xs):.0%} | {c[0] / len(xs):.0%} | "
                          f"{len(xs)} |")
    md.append("")
    for kind, label in (("diag_overall", "Chẩn đoán nhìn chung đúng với suy nghĩ của bạn"),
                        ("explain_overall", "Lời giải thích giúp bạn hiểu bài")):
        xs = [f["value"] for f in data["feedback"] if f["kind"] == kind and data["att_quiz"].get(f["attempt"]) == 1]
        if xs:
            lo, hi = boot_ci([float(x) for x in xs], rng)
            md.append(f"- **{label}** (1–5): trung bình {mean(xs):.2f} (CI 95% [{fmt(lo, 2)}; {fmt(hi, 2)}], n = {len(xs)}); "
                      f"phân bố {dict(sorted(Counter(xs).items()))}.")
    comments = [f["comment"] for f in data["feedback"] if f["kind"] == "comment" and f.get("comment")]
    if comments:
        md.append(f"- Góp ý tự do: {len(comments)} ý kiến (xem theo_sinh_vien.csv).")
    md.append("")
    return rows


def g5(data: dict, rng: random.Random, md: list[str]) -> list[dict]:
    md.append("## G5: vòng cá nhân hoá (nhóm A luyện điểm yếu, nhóm B luyện đề thường)\n")
    items, resp = data["items"], data["resp"]
    by = {k: defaultdict(dict) for k in (1, 2)}
    for k in (1, 2):
        for r in resp.get(k, []):
            by[k][r["user"]][items[r["question_id"]]["slide"]] = (r, items[r["question_id"]])
    rows = []
    for u, code in data["users"].items():
        if u not in by[1] or u not in by[2] or u not in data["practice"]:
            continue
        s1, s2 = data["scores"][(u, 1)], data["scores"][(u, 2)]
        wrong1 = {s: r for s, (r, _) in by[1][u].items() if not r["correct"]}
        fixed = [by[2][u][s][0]["correct"] for s in wrong1 if s in by[2][u]]
        opp = rep = 0
        for s, r in wrong1.items():
            e = r["error_type"]
            if not e or e == "khong_ro" or s not in by[2][u]:
                continue
            r2, info2 = by[2][u][s]
            if any(m.get("error_type") == e for m in info2["option_meta"].values() if m.get("role") == "distractor"):
                opp += 1
                rep += int(not r2["correct"] and r2["error_type"] == e)
        pr = data["practice"][u]
        rows.append({"ma": code, "nhom": data["group"][u], "diem_de1": s1, "diem_de2": s2,
                     "tien_bo": round(s2 - s1, 2), "so_slide_sai_de1": len(wrong1),
                     "ty_le_sua_duoc": round(mean(fixed), 4) if fixed else None,
                     "co_hoi_lap_lai": opp, "lap_lai": rep, "ty_le_lap_lai": round(rep / opp, 4) if opp else None,
                     "che_do_luyen": pr["mode"], "cau_nham_trung": pr["targeted"], "diem_luyen": pr["score"]})
    done = {g: [r for r in rows if r["nhom"] == g] for g in "AB"}
    md.append(f"Hoàn thành đủ 3 bước: nhóm A {len(done['A'])}, nhóm B {len(done['B'])} sinh viên.")
    fb_a = [r for r in done["A"] if r["che_do_luyen"] != "weakness"]
    if fb_a:
        md.append(f" Lưu ý: {len(fb_a)} người nhóm A chưa có điểm yếu nào sau Đề 1 nên đề luyện đã thành đề thường.")
    if done["A"]:
        md.append(f" Đề luyện của nhóm A trung bình có {mean(r['cau_nham_trung'] for r in done['A']):.1f} câu nhắm "
                  "trúng điểm yếu.")
    md.append("\n\n| Chỉ số | Nhóm A | Nhóm B | Hiệu A − B | CI 95% | p (Mann–Whitney) |\n|---|---|---|---|---|---|")
    for key, label in (("tien_bo", "Điểm Đề 2 − Đề 1 (thang 10)"), ("ty_le_sua_duoc", "Tỉ lệ sửa được slide đã sai"),
                       ("ty_le_lap_lai", "Tỉ lệ lặp lại đúng loại hiểu nhầm cũ")):
        a = [r[key] for r in done["A"] if r[key] is not None]
        b = [r[key] for r in done["B"] if r[key] is not None]
        if not a or not b:
            md.append(f"| {label} | {fmt(mean(a)) if a else '—'} | {fmt(mean(b)) if b else '—'} | — | — | — |")
            continue
        lo, hi = boot_diff(b, a, rng)
        p = None
        if len(a) >= 3 and len(b) >= 3:
            from scipy.stats import mannwhitneyu
            p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
        md.append(f"| {label} | {mean(a):.3f} (n={len(a)}) | {mean(b):.3f} (n={len(b)}) | {mean(a) - mean(b):+.3f} | "
                  f"[{fmt(lo)}; {fmt(hi)}] | {fmt(p, 4)} |")
    md.append("\nMẫu nhỏ và cả hai nhóm đều được xem lại Đề 1 kèm giải thích, nên kết quả chỉ mang tính mô tả; khoảng "
              "tin cậy rộng là bình thường. Tỉ lệ lặp lại chỉ tính trên các slide mà câu ở Đề 2 có phương án sai cùng "
              "loại hiểu nhầm người học đã mắc ở Đề 1.\n")
    useful = {g: [f["value"] for f in data["feedback"] if f["kind"] == "practice_useful" and data["group"].get(f["user"]) == g]
              for g in "AB"}
    if any(useful.values()):
        md.append("- Đề luyện tập có ích (1–5): " + " · ".join(
            f"nhóm {g}: {mean(xs):.2f} (n={len(xs)})" for g, xs in useful.items() if xs) + "\n")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="file cấu hình thử nghiệm (mặc định: thử nghiệm đang mở)")
    a = ap.parse_args()
    from app.experiment import config_path
    path = Path(a.config) if a.config else config_path()
    if not path.exists():
        raise SystemExit(f"Không thấy {path}. Thử nghiệm đã đóng thì truyền --config thu_nghiem_dong_*.json")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    data = load(cfg)
    rng = random.Random(42)
    md = [f"# Báo cáo thử nghiệm sinh viên ({cfg.get('name')}, tạo {cfg.get('created_at')})\n",
          f"{len(cfg['members'])} mã trong danh sách, {len(data['users'])} mã đã đăng nhập.\n"]
    item_rows = g4(data, rng, md)
    stu_rows = g5(data, rng, md)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if item_rows:
        write_csv(RESULTS / "phan_tich_cau.csv", item_rows)
    if G4_SUMMARY:
        write_csv(RESULTS / "g4_tong_hop.csv", G4_SUMMARY, list(dict.fromkeys(k for r in G4_SUMMARY for k in r)))
    if stu_rows:
        comments = defaultdict(list)
        for f in data["feedback"]:
            if f["kind"] == "comment" and f.get("comment"):
                comments[data["users"].get(f["user"])].append(f["comment"])
        write_csv(RESULTS / "theo_sinh_vien.csv", [{**r, "gop_y": " | ".join(comments.get(r["ma"], []))} for r in stu_rows])
    out = RESULTS / "bao_cao_sinh_vien.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
