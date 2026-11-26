"""Cột phải, chế độ Trắc nghiệm: tạo đề → làm bài (slide mờ đi) → chấm điểm → xem lại câu sai kèm trích dẫn."""
import time

import streamlit as st

import api_client as api
from views.left import call
from views.state import TAB_CHAT, S, attach_question, finish_quiz, go, open_right, reset_quiz, start_quiz
from views.theme import esc, html_block

MIN_Q, MAX_Q = 10, 50
PRESETS = ["10", "15", "20", "30", "Tự nhập"]
REVIEW_HEIGHT = 560
_NAMES: dict[int, str] = {}   # document_id → tên file (bỏ đuôi), cập nhật mỗi lần render


def _name(doc_id) -> str:
    return _NAMES.get(doc_id, "Bài đã xoá")


BLOOM_VI = {"remember": "Nhớ", "understand": "Hiểu", "apply": "Vận dụng"}


def _allocate(n: int, sizes: dict[int, int]) -> dict[int, int]:
    """Giống backend: chia n theo tỉ lệ số câu mỗi bài (phương pháp phần dư lớn nhất)."""
    total = sum(sizes.values()) or 1
    raw = {k: n * v / total for k, v in sizes.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: n - sum(out.values())]:
        out[k] += 1
    return out


# ---------------- Tạo đề ----------------
def _setup(docs: list[dict]) -> None:
    usable = [d for d in docs if d["status"] == "ready" and d["num_accepted"] > 0]
    html_block('<div class="field-label">Chọn slide để tạo đề</div>')
    selected = []
    with st.container(key="pick_docs"):
        if not docs:
            st.caption("Chưa có slide nào. Tải slide ở thanh bên trái.")
        for d in docs:
            ok = d in usable
            note = f"{d['num_accepted']} câu" if ok else ("đang xử lý" if d["status"] != "ready" else "chưa có câu hỏi")
            if st.checkbox(f"{_name(d['id'])}  ·  {note}", key=f"pick_{d['id']}",
                           value=ok and d["id"] == S.doc_id, disabled=not ok):
                selected.append(d["id"])

    sizes = {d["id"]: d["num_accepted"] for d in docs if d["id"] in selected}
    avail = sum(sizes.values())
    choice = st.segmented_control("Số câu hỏi", PRESETS, default="10", key="quiz_count") or "10"
    if choice == "Tự nhập":
        n = int(st.number_input("Nhập số câu", min_value=MIN_Q, max_value=MAX_Q, step=1,
                                value=max(MIN_Q, min(avail, MAX_Q)), key="quiz_custom_n"))
    else:
        n = int(choice)

    alloc = ""
    if len(sizes) > 1 and MIN_Q <= n <= avail:
        alloc = " · ".join(f"{esc(_name(k))}: {v}" for k, v in _allocate(n, sizes).items())
        alloc = f'<div class="alloc">Chia theo tỉ lệ câu của mỗi bài<br>{alloc}</div>'
    html_block(f'<div class="avail"><div><b>{avail}</b> câu có sẵn</div>{alloc}</div>'
               f'<div class="hint">Tối thiểu {MIN_Q} câu, tối đa {min(avail, MAX_Q) if avail else 0} câu '
               f'(số câu đang có trong phạm vi đã chọn). Thời gian làm bài: 1 phút / câu. '
               f'Cơ cấu mức độ: Nhớ 40% · Hiểu 40% · Vận dụng 20%.</div>')

    if st.button(f"Bắt đầu làm bài · {n} câu", type="primary", use_container_width=True, key="start_quiz"):
        err = ""
        if not selected:
            err = "Chọn ít nhất một bài đã có câu hỏi."
        elif avail < MIN_Q:
            err = f"Phạm vi đã chọn mới có {avail} câu, chưa đủ {MIN_Q}. Chọn thêm bài hoặc chờ hệ thống sinh thêm câu hỏi."
        elif n > avail:
            err = f"Phạm vi đã chọn chỉ có {avail} câu. Giảm số câu hoặc chọn thêm bài."
        if err:
            S.quiz_err = err
        else:
            quiz, e = call(api.create_quiz, {"document_ids": selected}, n)
            if e:
                S.quiz_err = e
            else:
                S.quiz_label = " + ".join(_name(d["id"]) for d in docs if d["id"] in selected)
                start_quiz(quiz)
                st.rerun()
    if S.quiz_err:
        st.error(S.quiz_err)

    hist = st.session_state.get("history", [])
    if hist:
        st.caption("Lần làm gần đây")
        for h in reversed(hist[-5:]):
            st.markdown(f"<div class='hint' style='display:flex;justify-content:space-between'>"
                        f"<span>{esc(h['label'])} · {h['n']} câu</span><b style='font-family:var(--mono)'>"
                        f"{h['score']:.1f}</b></div>", unsafe_allow_html=True)


# ---------------- Làm bài ----------------
@st.fragment(run_every=1)
def _timer() -> None:
    left = int((S.deadline or time.time()) - time.time())
    if left <= 0:
        html_block('<span class="timer low">Hết giờ · hãy nộp bài</span>')
    else:
        html_block(f'<span class="timer {"low" if left < 60 else ""}">⏱ {left // 60:02d}:{left % 60:02d}</span>')


def _submit() -> None:
    qs = S.quiz["questions"]
    missing = [i for i, q in enumerate(qs) if q["question_id"] not in S.answers]
    if missing:
        S.quiz_err = f"Còn {len(missing)} câu chưa trả lời: câu {', '.join(str(i + 1) for i in missing)}."
        S.qi = missing[0]
        return
    attempt, err = call(api.submit_attempt, S.quiz["quiz_id"], S.answers)
    if err:
        S.quiz_err = err
        return
    review, err = call(api.get_review, attempt["attempt_id"])
    if err:
        S.quiz_err = err
        return
    st.session_state.setdefault("history", []).append(
        {"label": st.session_state.get("quiz_label", "Đề"), "n": attempt["num_questions"], "score": attempt["score_10"]})
    finish_quiz(attempt, review)


def _taking() -> None:
    qs = S.quiz["questions"]
    total, done = len(qs), sum(1 for q in qs if q["question_id"] in S.answers)
    h1, h2 = st.columns([3, 1.3], vertical_alignment="center")
    h1.markdown(f'<div class="qtop"><b>Đề {esc(st.session_state.get("quiz_label", ""))} · {total} câu</b></div>',
                unsafe_allow_html=True)
    with h2:
        _timer()
    html_block(f'<div class="hint">Đã làm {done}/{total} câu</div><div class="bar"><i style="width:{done / total * 100:.0f}%">'
               f'</i></div>')

    with st.container(key="palette"):
        for start in range(0, total, 10):
            cols = st.columns(10)
            for j, col in enumerate(cols):
                k = start + j
                if k >= total:
                    continue
                answered = qs[k]["question_id"] in S.answers
                label = f"›{k + 1}" if k == S.qi else str(k + 1)
                if col.button(label, key=f"pal_{k}", type="primary" if answered else "secondary",
                              use_container_width=True):
                    S.qi = k
                    st.rerun()

    q = qs[S.qi]
    lvl = BLOOM_VI.get(q.get("bloom_level") or "", "")
    html_block(f'<div class="qn">CÂU {S.qi + 1}/{total}{f"<span class=lvl>{lvl}</span>" if lvl else ""}</div>'
               f'<div class="stem">{esc(q["stem"])}</div>')
    with st.container(key="options"):
        for letter, text in q["options"].items():
            chosen = S.answers.get(q["question_id"]) == letter
            if st.button(f"**{letter}.** {text}", key=f"opt_{q['question_id']}_{letter}",
                         type="primary" if chosen else "secondary", use_container_width=True):
                S.answers[q["question_id"]] = letter
                S.quiz_err = ""
                if S.qi < total - 1:
                    S.qi += 1
                st.rerun()
    if S.quiz_err:
        st.error(S.quiz_err)

    n1, n2, n3 = st.columns([1, 1, 1.2])
    if n1.button("‹ Câu trước", use_container_width=True, disabled=S.qi == 0, key="q_prev"):
        S.qi -= 1
        st.rerun()
    if n2.button("Câu sau ›", use_container_width=True, disabled=S.qi >= total - 1, key="q_next"):
        S.qi += 1
        st.rerun()
    if n3.button("Nộp bài", type="primary", use_container_width=True, key="q_submit"):
        _submit()
        st.rerun()


# ---------------- Kết quả và xem lại ----------------
def _option_rows(item: dict) -> str:
    rows = []
    for letter, text in item["options"].items():
        right, mine = letter == item["answer"], letter == item["chosen"]
        cls = "right" if right else ("wrong" if mine else "")
        why = ("Đáp án đúng" + (" · bạn chọn" if mine else "")) if right else ("Bạn chọn" if mine else "")
        rows.append(f'<div class="ropt {cls}"><span class="L">{letter}</span><span>{esc(text)}</span>'
                    f'{f"<span class=why>{why}</span>" if why else ""}</div>')
        if right or mine:
            rows.append(f'<div class="rat">{esc(item["rationales"].get(letter, ""))}</div>')
    return "".join(rows)


def _evidence_html(item: dict) -> str:
    src = item["sources"][0] if item.get("sources") else None
    if item.get("evidence"):
        slide = item.get("evidence_slide_no") or (src and src["slide_no"])
        doc_id = item.get("evidence_document_id") or (src and src["document_id"])
        where = f"{esc(_name(doc_id))} · Slide {slide}" + (f" — {esc(src['title'])}" if src and src.get("title") else "")
        return (f'<div class="evid"><div class="eh">Trích dẫn từ slide<span class="ver">✓ Khớp nguyên văn với slide</span></div>'
                f'<div class="eb"><p class="quote">“<mark>{esc(item["evidence"])}</mark>”</p>'
                f'<div class="srcline">{where}</div></div></div>')
    if src:
        snippet = esc((src.get("raw_text") or "")[:260])
        return (f'<div class="evid"><div class="eh">Slide nguồn<span class="ver no">Câu hỏi sinh trước khi có trích dẫn</span></div>'
                f'<div class="eb"><p class="quote">{snippet}…</p><div class="srcline">{esc(_name(src["document_id"]))} · Slide '
                f'{src["slide_no"]}{" — " + esc(src["title"]) if src.get("title") else ""}</div></div></div>')
    return ""


def _review() -> None:
    rv, at = S.review, S.attempt
    items = rv["items"]
    right = sum(1 for i in items if i["is_correct"])
    pct = right / len(items) * 100 if items else 0
    html_block(f'<div class="score"><div class="ring" style="background:conic-gradient(var(--brand) {pct:.0f}%,'
               f'var(--brand-100) 0)"><div><span><b>{at["score_10"]:.1f}</b><br><small>/ 10</small></span></div></div>'
               f'<div><b>Đã chấm xong</b><div class="hint">{esc(st.session_state.get("quiz_label", ""))} · '
               f'{len(items)} câu</div><div style="margin-top:6px"><span class="stat ok"><b>{right}</b> đúng</span>'
               f'<span class="stat bad"><b>{len(items) - right}</b> sai</span></div></div></div>')
    c1, c2 = st.columns(2)
    if c1.button("Làm đề mới", type="primary", use_container_width=True, key="again"):
        reset_quiz()
        st.rerun()
    if c2.button("Đóng kết quả", use_container_width=True, key="close_review"):
        reset_quiz()
        open_right(TAB_CHAT)
        st.rerun()

    filt = st.segmented_control("Xem lại", ["Câu sai", "Tất cả"], key="review_filter") or "Câu sai"
    shown = [(i, it) for i, it in enumerate(items) if filt == "Tất cả" or not it["is_correct"]]
    if not shown:
        st.success("Bạn không sai câu nào. Chọn “Tất cả” để xem lại toàn bộ đề.")
    # Danh sách cuộn riêng trong cột phải để trang không cuộn mất slide khi bấm "Xem trên slide"
    box = st.container(height=REVIEW_HEIGHT, border=False, key="review_box")
    for i, it in shown:
        with box, st.container(border=True, key=f"rv_{it['question_id']}"):
            lvl = BLOOM_VI.get(it.get("bloom_level") or "", "")
            viewing = '<span class="viewing-tag">● Đang hiện trên slide</span>' if S.viewing == it["question_id"] else ""
            lvl_tag = f"<span class=lvl>{lvl}</span>" if lvl else ""
            res_cls, res_txt = ("ok", "Đúng") if it["is_correct"] else ("bad", "Sai")
            expl = f"<div class=expl><b>Giải thích:</b> {esc(it['explanation'])}</div>" if it.get("explanation") else ""
            html_block(f'<div class="qn">CÂU {i + 1}{lvl_tag}<span class="res {res_cls}">{res_txt}</span>'
                       f'{viewing}</div><div class="stem">{esc(it["stem"])}</div>{_option_rows(it)}'
                       f'{expl}{_evidence_html(it)}')
            src = it["sources"][0] if it.get("sources") else None
            doc_id = it.get("evidence_document_id") or (src and src["document_id"])
            slide = it.get("evidence_slide_no") or (src and src["slide_no"])
            b1, b2 = st.columns(2)
            if doc_id and doc_id not in _NAMES:
                b1.caption("Bài này đã bị xoá nên không mở được slide.")
            elif doc_id and b1.button("Xem trên slide", icon=":material/slideshow:", key=f"view_{it['question_id']}",
                                    type="primary", use_container_width=True):
                go(doc_id, slide, it.get("evidence"), viewing=it["question_id"])
                st.rerun()
            if b2.button("Hỏi trợ lý về câu này", icon=":material/chat:", key=f"askq_{it['question_id']}",
                         use_container_width=True):
                attach_question(it, i)
                st.rerun()


def render(docs: list[dict]) -> None:
    _NAMES.clear()
    _NAMES.update({d["id"]: d["filename"].rsplit(".", 1)[0] for d in docs})
    {"setup": lambda: _setup(docs), "taking": _taking, "review": _review}[S.quiz_mode]()
