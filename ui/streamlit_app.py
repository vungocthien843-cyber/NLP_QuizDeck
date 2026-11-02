"""Giao diện học tập một trang, 3 cột:
  trái  – tải slide, tiến trình xử lý, danh sách bài đã tải (thu gọn được)
  giữa  – xem slide; tô vàng câu trích khi đối chiếu; mờ đi khi đang làm bài
  phải  – Trợ lý AI (chat có trích dẫn, đính kèm câu hỏi) / Trắc nghiệm (tạo đề, làm bài, xem lại)
Chạy: streamlit run ui/streamlit_app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api_client as api  # noqa: E402
from views import center, chat, left, quiz  # noqa: E402
from views.state import TAB_CHAT, TAB_QUIZ, S, apply_tab_request, init, open_right  # noqa: E402
from views.theme import header, inject_css  # noqa: E402

st.set_page_config(page_title="ICTU · Trợ lý học tập", page_icon=str(Path(__file__).parent / "assets" / "logo_ictu.jpg"),
                   layout="wide", initial_sidebar_state="collapsed")
init()
apply_tab_request()
inject_css()
header()

docs, err = left.call(api.list_documents)
if err:
    st.error(err)
    docs = []


def _widths() -> list[float]:
    lw = 0.21 if S.left_open else 0.045
    if not S.right_open:
        rw = 0.045
    elif S.quiz_mode in ("taking", "review") and S.right_tab == TAB_QUIZ:
        rw = 0.37
    else:
        rw = 0.29
    return [lw, 1 - lw - rw, rw]


def _right_panel() -> None:
    if not S.right_open:
        if st.button("", icon=":material/right_panel_open:", key="open_right", help="Mở thanh trợ lý"):
            S.right_open = True
            st.rerun()
        if st.button("", icon=":material/chat:", key="rail_chat", help="Trợ lý AI"):
            open_right(TAB_CHAT)
            st.rerun()
        if st.button("", icon=":material/quiz:", key="rail_quiz", help="Trắc nghiệm"):
            open_right(TAB_QUIZ)
            st.rerun()
        return
    c1, c2 = st.columns([1, 6], vertical_alignment="center")
    if c1.button("", icon=":material/right_panel_close:", key="close_right", help="Thu gọn thanh phải"):
        S.right_open = False
        st.rerun()
    badge = {"taking": " · đang làm", "review": " · kết quả"}.get(S.quiz_mode, "")
    with c2:
        st.segmented_control("Chế độ", [TAB_CHAT, TAB_QUIZ], key="right_tab", label_visibility="collapsed",
                             format_func=lambda t: t + badge if t == TAB_QUIZ else t)
    tab = S.right_tab or TAB_CHAT    # bấm lại tab đang chọn sẽ bỏ chọn → coi như Trợ lý AI
    if tab == TAB_QUIZ:
        quiz.render(docs)
    else:
        ready = [d for d in docs if d["status"] == "ready"]
        chat.render(f"tất cả slide đã tải lên ({len(ready)} bài)")


col_l, col_c, col_r = st.columns(_widths(), gap="small")
with col_l, st.container(key="left_panel"):
    left.render(docs)
with col_c, st.container(key="center_panel"):
    center.render(docs)
with col_r, st.container(key="right_panel"):
    _right_panel()
