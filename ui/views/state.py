"""Trạng thái giao diện (st.session_state) và các thao tác đổi trạng thái dùng chung giữa các cột."""
import time

import streamlit as st

TAB_CHAT = "Trợ lý AI"
TAB_QUIZ = "Trắc nghiệm"
SECONDS_PER_QUESTION = 60          # thời gian làm bài = 1 phút / câu

DEFAULTS = {
    "left_open": True,
    "right_open": True,
    "doc_id": None,          # bài đang xem ở giữa
    "slide": 1,
    "highlight": None,       # đoạn văn đang tô vàng trên slide
    "viewing": None,         # question_id đang đối chiếu trên slide (từ phần xem lại)
    "right_tab": TAB_CHAT,   # key của widget chọn chế độ; KHÔNG gán trực tiếp sau khi widget đã vẽ
    "tab_req": None,         # yêu cầu đổi chế độ, áp dụng ở đầu lượt chạy kế tiếp (apply_tab_request)
    "quiz_mode": "setup",    # setup | taking | review
    "quiz": None,
    "answers": {},           # question_id -> chữ cái
    "qi": 0,                 # câu đang hiển thị khi làm bài
    "deadline": None,
    "attempt": None,
    "review": None,
    "review_filter": "Câu sai",
    "quiz_err": "",
    "chat_conv": None,
    "chat_msgs": [],         # {"role", "content", "citations", "attach"}
    "attach": None,          # câu trắc nghiệm đính kèm tin nhắn tiếp theo
    "pending_prompt": None,  # câu hỏi gợi ý được bấm, gửi ở lượt chạy kế tiếp
    "confirm_delete": None,  # id bài đang chờ xác nhận xoá
}


def init() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v


S = st.session_state


def go(doc_id: int, slide: int, highlight: str | None = None, viewing: int | None = None) -> None:
    """Mở slide ở cột giữa; giữ nguyên cột phải (bộ câu hỏi đang soát không mất)."""
    S.doc_id, S.slide, S.highlight, S.viewing = doc_id, max(1, int(slide)), highlight, viewing
    S.jump_seq = S.get("jump_seq", 0) + 1     # buộc khung slide tải lại và cuộn tới slide này


def clear_highlight() -> None:
    S.highlight, S.viewing = None, None


def open_right(tab: str) -> None:
    if tab == TAB_CHAT and S.quiz_mode == "taking":
        return
    S.right_open = True
    S.tab_req = tab


def apply_tab_request() -> None:
    """Gọi ở đầu script, trước khi vẽ widget chọn chế độ."""
    if S.tab_req:
        S.right_tab, S.tab_req = S.tab_req, None


def start_quiz(quiz: dict) -> None:
    S.quiz, S.answers, S.qi, S.quiz_err = quiz, {}, 0, ""
    S.attempt = S.review = None
    S.quiz_mode = "taking"
    S.deadline = time.time() + SECONDS_PER_QUESTION * max(1, quiz["num_questions"])
    S.attach = None
    clear_highlight()
    open_right(TAB_QUIZ)


def finish_quiz(attempt: dict, review: dict) -> None:
    S.attempt, S.review = attempt, review
    S.quiz_mode = "review"
    S.review_filter = "Câu sai"


def reset_quiz() -> None:
    S.quiz_mode, S.quiz, S.attempt, S.review, S.answers, S.quiz_err = "setup", None, None, None, {}, ""
    clear_highlight()


def attach_question(item: dict, index: int) -> None:
    """Đính kèm một câu đã làm vào ô chat (người học vẫn tự gõ câu hỏi)."""
    S.attach = {
        "question_id": item["question_id"],
        "attempt_id": S.attempt["attempt_id"] if S.attempt else None,
        "index": index,
        "stem": item["stem"],
        "chosen": item.get("chosen"),
        "answer": item["answer"],
        "is_correct": item["is_correct"],
        "slide_no": item.get("evidence_slide_no") or (item["sources"][0]["slide_no"] if item.get("sources") else None),
    }
    open_right(TAB_CHAT)


def new_chat() -> None:
    S.chat_conv, S.chat_msgs, S.attach, S.pending_prompt = None, [], None, None
