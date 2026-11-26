"""Thử nghiệm với sinh viên (Mốc 3, G4/G5) trong cột Trắc nghiệm.

Chỉ hiện khi đang có thử nghiệm và mã người học nằm trong danh sách. Ba bước: Đề 1 → Luyện tập → Đề 2, kèm khảo sát
ngắn. Người học không thấy mình thuộc nhóm nào (giao diện chỉ ghi "Luyện tập").
"""
import streamlit as st

import api_client as api
from views.left import call
from views.state import S, start_quiz
from views.theme import html_block

DIAG_CHOICES = {"Đúng": 2, "Một phần": 1, "Không đúng": 0}
LIKERT = [1, 2, 3, 4, 5]
LIKERT_HELP = "1 = hoàn toàn không · 3 = bình thường · 5 = hoàn toàn đúng"


def state() -> dict | None:
    """Trạng thái thử nghiệm của người học đang đăng nhập; None nếu không tham gia."""
    if not S.user:
        return None
    st_, err = call(api.experiment_state, S.user["user_id"])
    if err or not st_ or not st_.get("active") or not st_.get("member"):
        S.exp = None
        return None
    S.exp = st_
    return st_


def _start(quiz: dict, label: str) -> None:
    S.quiz_label = label
    start_quiz(quiz)
    S.quiz_notice = None
    st.rerun()


def box() -> bool:
    """Khung 3 bước ở đầu phần tạo đề. Trả True khi người học đang giữa thử nghiệm (ẩn phần tạo đề tự do)."""
    ex = state()
    if not ex:
        return False
    step = ex["step"]
    marks = {s: ("✅" if (step == "done" or s < step) else "👉" if s == step else "⬜") for s in "123"}
    html_block(f"<div class='hint' style='padding:10px 12px;border:1px solid var(--brand-100);border-radius:10px;"
               f"margin-bottom:10px'><b>🧪 Thử nghiệm hệ thống ôn tập</b><br>"
               f"{marks['1']} Bước 1 · Làm Đề 1<br>{marks['2']} Bước 2 · Luyện tập ({ex['practice_n']} câu)<br>"
               f"{marks['3']} Bước 3 · Làm Đề 2</div>")
    uid = S.user["user_id"]
    if step == "1":
        st.caption("Làm bài nghiêm túc, không xem slide hay tài liệu. Sau khi nộp, xem lại các câu sai và trả lời "
                   "khảo sát ngắn ở phần kết quả.")
        if st.button("Bắt đầu Đề 1", type="primary", use_container_width=True, key="exp_q1"):
            quiz, err = call(api.get_quiz, ex["quiz1_id"])
            if err:
                st.error(err)
            else:
                _start(quiz, "Thử nghiệm · Đề 1")
    elif step == "2":
        a1 = str(ex["attempt1_id"])
        if not {"diag_overall", "explain_overall"} <= set(ex["feedback_kinds"].get(a1, [])):
            st.info("Trước khi luyện tập, hãy trả lời 2 câu khảo sát về Đề 1:")
            overall_survey(ex["attempt1_id"], key="box")
            return True
        if ex.get("practice_quiz_id"):
            st.caption("Bạn có một đề luyện tập đang làm dở.")
        if st.button("Bắt đầu luyện tập", type="primary", use_container_width=True, key="exp_pr"):
            quiz, err = call(api.experiment_practice, uid)
            if err:
                st.error(err)
            else:
                _start(quiz, "Thử nghiệm · Luyện tập")
    elif step == "3":
        st.caption("Bước cuối. Làm bài nghiêm túc như Đề 1.")
        if st.button("Bắt đầu Đề 2", type="primary", use_container_width=True, key="exp_q2"):
            quiz, err = call(api.get_quiz, ex["quiz2_id"])
            if err:
                st.error(err)
            else:
                _start(quiz, "Thử nghiệm · Đề 2")
    else:
        st.success("Bạn đã hoàn thành thử nghiệm. Cảm ơn bạn! Bạn có thể tiếp tục tự ôn tập bên dưới.")
        return False
    return True


def overall_survey(attempt_id: int, key: str) -> None:
    with st.form(f"survey_{key}_{attempt_id}", border=True):
        d = st.radio("Phần “Có thể bạn đang nhầm” nhìn chung có đúng với điều bạn đã nghĩ khi chọn sai không?",
                     LIKERT, index=None, horizontal=True, help=LIKERT_HELP)
        e = st.radio("Lời giải thích và trích dẫn slide có giúp bạn hiểu bài hơn không?", LIKERT, index=None,
                     horizontal=True, help=LIKERT_HELP)
        if st.form_submit_button("Gửi khảo sát", type="primary", use_container_width=True):
            if d is None or e is None:
                st.error("Chọn mức cho cả hai câu.")
                return
            uid = S.user["user_id"]
            for kind, v in (("diag_overall", d), ("explain_overall", e)):
                _, err = call(api.send_feedback, uid, attempt_id, kind, v)
                if err:
                    st.error(err)
                    return
            st.rerun()


def _which(ex: dict) -> str | None:
    qid = (S.quiz or {}).get("quiz_id")
    if qid == ex["quiz1_id"]:
        return "1"
    if qid == ex["quiz2_id"]:
        return "3"
    if (S.get("quiz_label") or "").endswith("Luyện tập"):
        return "2"
    return None


def review_top() -> None:
    """Khảo sát ngắn ở đầu trang kết quả của từng bước."""
    ex = state()
    if not ex or not S.attempt:
        return
    which, att = _which(ex), S.attempt["attempt_id"]
    done = set(ex["feedback_kinds"].get(str(att), []))
    uid = S.user["user_id"]
    if which == "1":
        html_block("<div class='hint'>🧪 Ở mỗi câu sai có chẩn đoán, hãy cho biết chẩn đoán có đúng với điều bạn "
                   "đã nghĩ không. Sau đó trả lời 2 câu khảo sát bên dưới.</div>")
        if {"diag_overall", "explain_overall"} <= done:
            st.success("Đã ghi khảo sát Đề 1. Cảm ơn bạn! Bấm “Làm đề mới” để sang bước Luyện tập.")
        else:
            overall_survey(att, key="review")
    elif which == "2" and "practice_useful" not in done:
        with st.form(f"survey_pr_{att}"):
            v = st.radio("Đề luyện tập này có giúp bạn ôn đúng chỗ còn yếu không?", LIKERT, index=None,
                         horizontal=True, help=LIKERT_HELP)
            if st.form_submit_button("Gửi", type="primary", use_container_width=True) and v is not None:
                call(api.send_feedback, uid, att, "practice_useful", v)
                st.rerun()
    elif which == "3" and "comment" not in done:
        with st.form(f"survey_cm_{att}"):
            t = st.text_area("Góp ý của bạn về hệ thống (không bắt buộc)", max_chars=2000)
            if st.form_submit_button("Gửi góp ý", use_container_width=True):
                call(api.send_feedback, uid, att, "comment", None, None, t.strip() or "(không góp ý)")
                st.rerun()


def _send_item(attempt_id: int, question_id: int, key: str) -> None:
    v = st.session_state.get(key)
    if v in DIAG_CHOICES:
        call(api.send_feedback, S.user["user_id"], attempt_id, "diag_item", DIAG_CHOICES[v], question_id)


def item_feedback(it: dict) -> None:
    """Đề 1: hỏi chẩn đoán của từng câu sai có đúng ý người học không."""
    ex = S.get("exp")
    if not ex or not S.attempt or _which(ex) != "1" or it.get("is_correct") or not it.get("misconception"):
        return
    att = S.attempt["attempt_id"]
    key = f"fbi_{att}_{it['question_id']}"
    st.radio("Chẩn đoán này có đúng với điều bạn đã nghĩ khi chọn?", list(DIAG_CHOICES), index=None,
             horizontal=True, key=key, on_change=_send_item, args=(att, it["question_id"], key))
