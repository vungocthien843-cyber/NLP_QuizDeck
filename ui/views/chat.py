"""Cột phải, chế độ Trợ lý AI: chat có trích dẫn; có thể đính kèm một câu trắc nghiệm vào tin nhắn."""
import streamlit as st
import streamlit.components.v1 as components

import api_client as api
from views.state import S, go, new_chat
from views.theme import esc, html_block

CHAT_HEIGHT = 500
SUGGESTIONS = ["Tóm tắt các ý chính của bài học", "Giải thích một khái niệm khó trong bài", "Cho ví dụ minh hoạ dễ hiểu"]


def _sources(msg_index: int, citations: list[dict]) -> None:
    """Danh sách nguồn dưới câu trả lời; bấm để mở đúng slide ở cột giữa."""
    cites = [c for c in citations if c.get("document_id")]
    if not cites:
        return
    html_block('<div class="src-head">Nguồn</div>')
    with st.container(key=f"cites_{msg_index}"):
        for c in cites:
            title = f" · {c['title'][:52]}" if c.get("title") else ""
            where = c.get("filename") or "Tài liệu"
            if st.button(f"[{c['n']}]  {where} · Slide {c.get('slide_no')}{title}",
                         key=f"cite_{msg_index}_{c['n']}", help="Mở slide này ở giữa", use_container_width=True):
                go(c["document_id"], c.get("slide_no") or 1)
                st.rerun()


_SCROLL_JS = """<script>/* __N__ */
  const box = window.parent.document.querySelector('.st-key-chat_box');
  // chỉ tìm vùng cuộn của chính khung chat (tối đa 3 cấp), không cuộn cả trang
  let e = box;
  for (let k = 0; k < 3 && e; k++, e = e.parentElement) {
    const oy = getComputedStyle(e).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && e.scrollHeight > e.clientHeight + 2) { e.scrollTop = e.scrollHeight; break; }
  }
</script>"""


def _scroll_to_bottom(n: int) -> None:
    """Cuộn khung chat xuống tin mới nhất (iframe ẩn, cùng origin nên truy cập được trang cha)."""
    components.html(_SCROLL_JS.replace("__N__", str(n)), height=0)


def _attach_quote(a: dict) -> str:
    return f'<div class="att-in-msg">Câu {a["index"] + 1} · {esc(a["stem"])}</div>'


def _message(i: int, m: dict) -> None:
    if m["role"] == "user":
        with st.container(key=f"msgu_{i}"):
            if m.get("attach"):
                html_block(_attach_quote(m["attach"]))
            st.markdown(m["content"])
        return
    with st.container(key=f"msga_{i}"):
        html_block('<div class="who">Trợ lý học tập</div>')
        if m.get("content"):
            st.markdown(m["content"])
        if m.get("error"):
            html_block(f'<div class="msg-err">Không nhận được câu trả lời: {esc(m["error"])}</div>')
        _sources(i, m.get("citations") or [])


def _send(prompt: str, box) -> None:
    att = S.attach
    S.chat_msgs.append({"role": "user", "content": prompt, "citations": [], "attach": att})
    i = len(S.chat_msgs)
    with box:
        _message(i - 1, S.chat_msgs[-1])
        citations: list[dict] = []
        errors: list[str] = []
        answer = ""
        try:
            conv, events = api.chat_stream(prompt, S.chat_conv, att and att["attempt_id"], att and att["question_id"])
            S.chat_conv = conv

            def tokens():
                for ev in events:
                    if ev["type"] == "token":
                        yield ev["text"]
                    elif ev["type"] == "done":
                        citations.extend(ev.get("citations", []))
                    elif ev["type"] == "error":
                        errors.append(ev["message"])

            with st.container(key=f"msga_{i}"):
                html_block('<div class="who">Trợ lý học tập</div>')
                answer = st.write_stream(tokens()) or ""
        except api.ApiError as exc:
            errors.append(str(exc))
        except Exception:
            errors.append(f"không kết nối được backend tại {api.API_BASE_URL}.")
    if not answer and not errors:
        errors.append("mô hình trả về nội dung rỗng. Kiểm tra OPENAI_API_KEY và tên model trong config.yaml.")
    S.chat_msgs.append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(answer),
                        "citations": citations, "attach": None, "error": "; ".join(errors) or None})
    S.attach = None
    st.rerun()


def render(scope_label: str) -> None:
    if S.quiz_mode == "taking":
        html_block('<div class="locked">Trợ lý tạm khoá trong lúc làm bài. Nộp bài xong bạn có thể hỏi về '
                   'từng câu, kể cả câu làm sai.</div>')
        return
    c1, c2 = st.columns([6, 1], vertical_alignment="center")
    c1.markdown(f'<div class="scope">Trả lời dựa trên {esc(scope_label)}</div>', unsafe_allow_html=True)
    if c2.button("", icon=":material/add_comment:", key="new_chat", use_container_width=True,
                 disabled=not S.chat_msgs, help="Bắt đầu hội thoại mới"):
        new_chat()
        st.rerun()

    box = st.container(height=CHAT_HEIGHT, border=False, key="chat_box")
    with box:
        if not S.chat_msgs and not S.attach:
            html_block('<div class="chat-empty"><b>Hỏi đáp về bài giảng</b>Câu trả lời được tổng hợp từ slide đã tải lên '
                       'và luôn kèm nguồn. Bấm vào nguồn để mở đúng slide.</div>')
            with st.container(key="suggest"):
                for s in SUGGESTIONS:
                    if st.button(s, key=f"sg_{s}", use_container_width=True):
                        S.pending_prompt = s
                        st.rerun()
        for i, m in enumerate(S.chat_msgs):
            _message(i, m)
        if S.chat_msgs:
            _scroll_to_bottom(len(S.chat_msgs))

    if S.attach:
        a = S.attach
        a1, a2 = st.columns([8, 1], vertical_alignment="top")
        state = "đúng" if a["is_correct"] else "sai"
        where = f" · Slide {a['slide_no']}" if a.get("slide_no") else ""
        a1.markdown(f'<div class="attach"><div><b>Đính kèm · Câu {a["index"] + 1} ({state})</b>{esc(a["stem"])}'
                    f'<div class="ans">Bạn chọn {a.get("chosen") or "—"} · Đáp án đúng {a["answer"]}{where}</div></div></div>',
                    unsafe_allow_html=True)
        if a2.button("", icon=":material/close:", key="rm_attach", help="Bỏ đính kèm"):
            S.attach = None
            st.rerun()
        tips = ([] if a["is_correct"] else [f"Vì sao chọn {a.get('chosen')} là sai?"]) + \
            ["Giải thích kỹ hơn bằng ví dụ", "Cho mình một câu tương tự để luyện"]
        with st.container(key="tips"):
            cols = st.columns(len(tips))
            for col, tip in zip(cols, tips):
                if col.button(tip, key=f"tip_{tip}", use_container_width=True):
                    S.pending_prompt = tip
                    st.rerun()

    placeholder = "Nhập câu hỏi về câu trắc nghiệm này…" if S.attach else "Đặt câu hỏi về nội dung bài giảng…"
    prompt = st.chat_input(placeholder, key="chat_input")
    if not prompt and S.pending_prompt:
        prompt, S.pending_prompt = S.pending_prompt, None
    if prompt:
        _send(prompt, box)
