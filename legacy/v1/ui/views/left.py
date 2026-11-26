"""Cột trái: tải slide lên, tiến trình xử lý, danh sách bài đã tải (thu gọn, bấm mới hiện)."""
import streamlit as st

import api_client as api
from views.state import S, go
from views.theme import esc, html_block

STEP_LABELS = [("parsing", "Đọc slide"), ("embedding", "Chia đoạn"), ("generating", "Sinh câu hỏi")]
PROCESSING = {"uploaded", "parsing", "embedding", "generating"}


def call(fn, *args, **kwargs):
    """Gọi API, trả (kết quả, thông báo lỗi) để hiện lỗi tại chỗ thay vì dừng cả trang."""
    try:
        return fn(*args, **kwargs), None
    except api.ApiError as exc:
        return None, str(exc)
    except Exception:
        return None, f"Không kết nối được backend tại {api.API_BASE_URL}."


def _steps(doc: dict) -> str:
    order = [s for s, _ in STEP_LABELS]
    cur = order.index(doc["status"]) if doc["status"] in order else 0
    parts = []
    for i, (_, label) in enumerate(STEP_LABELS):
        if i < cur:
            parts.append(f'<span class="done">{label} ✓</span>')
        elif i == cur:
            extra = f" ({doc['num_accepted']} câu)" if doc["status"] == "generating" else ""
            parts.append(f'<span class="now">{label}{extra}…</span>')
        else:
            parts.append(f"<span>{label}</span>")
    return "·".join(parts)


def _job_cards(docs: list[dict]) -> None:
    for d in docs:
        if d["status"] in PROCESSING:
            html_block(f'<div class="job"><div class="n"><span>{esc(d["filename"])}</span>'
                       f'<span class="pill run">Đang xử lý</span></div><div class="steps">{_steps(d)}</div></div>')
        elif d["status"] == "failed":
            html_block(f'<div class="job"><div class="n"><span>{esc(d["filename"])}</span>'
                       f'<span class="pill bad">Lỗi</span></div><div class="steps">{esc(d["error"])}</div></div>')


@st.fragment(run_every=4)
def _watch_jobs(signature: str) -> None:
    """Tự cập nhật tiến trình mỗi 4 giây; khi có bài xử lý xong thì chạy lại cả trang."""
    docs, err = call(api.list_documents)
    if err or docs is None:
        return
    now = "|".join(f"{d['id']}:{d['status']}" for d in docs)
    if now != signature:
        st.rerun(scope="app")
    _job_cards(docs)


def _upload() -> None:
    html_block('<div class="sec-title">⇪ Tải lên slide</div>')
    key = f"uploader_{st.session_state.get('upload_round', 0)}"
    file = st.file_uploader("Chọn file slide", type=["pptx", "pdf"], key=key, label_visibility="collapsed",
                            help=".pptx hoặc .pdf, tối đa 50 MB")
    if st.button("Tải lên", type="primary", use_container_width=True, key="btn_upload", disabled=not file):
        if not file:
            st.error("Chọn file .pptx hoặc .pdf trước khi tải lên.")
        else:
            doc, err = call(api.upload_document, file.name, file.getvalue())
            if err:
                st.error(err)
            else:
                st.session_state["upload_round"] = st.session_state.get("upload_round", 0) + 1
                st.toast(f"Đã nhận {doc['filename']}. Hệ thống đang đọc slide và sinh câu hỏi.")
                st.rerun()


def _confirm_delete(d: dict) -> None:
    name = esc(d["filename"].rsplit(".", 1)[0])
    with st.container(key="confirm_box"):
        html_block(f'<div class="confirm"><b>Xoá “{name}”?</b>Bài sẽ biến mất khỏi thư viện, không dùng để tạo đề '
                   f'và trả lời chat nữa. Điểm các lần làm bài trước vẫn được giữ.</div>')
        b1, b2 = st.columns(2)
        if b1.button("Xoá", type="primary", use_container_width=True, key="del_yes"):
            _, err = call(api.delete_document, d["id"])
            S.confirm_delete = None
            if err:
                st.session_state["delete_err"] = err
            else:
                if S.doc_id == d["id"]:
                    S.doc_id, S.slide, S.highlight, S.viewing = None, 1, None, None
                st.session_state.pop(f"pick_{d['id']}", None)
                st.toast(f"Đã xoá {d['filename']}.")
            st.rerun()
        if b2.button("Huỷ", use_container_width=True, key="del_no"):
            S.confirm_delete = None
            st.rerun()


def _library(docs: list[dict]) -> None:
    ready = [d for d in docs if d["status"] not in PROCESSING]
    # sau khi bấm thùng rác thì giữ danh sách mở (huỷ/xoá xong vẫn thấy danh sách)
    keep_open = S.confirm_delete is not None or bool(st.session_state.get("lib_open"))
    with st.expander(f"Slide đã tải lên ({len(docs)})", expanded=keep_open, icon=":material/folder:"):
        if not docs:
            st.caption("Chưa có bài nào. Tải slide đầu tiên ở trên.")
        for d in docs:
            pill = {"ready": ("ok", "Sẵn sàng"), "failed": ("bad", "Lỗi")}.get(d["status"], ("run", "Đang xử lý"))
            c1, c2, c3 = st.columns([5, 2, 1], vertical_alignment="center")
            label = d["filename"].rsplit(".", 1)[0]
            if c1.button(label, key=f"doc_{d['id']}", use_container_width=True,
                         type="primary" if d["id"] == S.doc_id else "secondary",
                         disabled=d["num_slides"] == 0):
                go(d["id"], 1)
                st.rerun()
            c2.markdown(f'<span class="pill {pill[0]}">{pill[1]}</span>', unsafe_allow_html=True)
            busy = d["status"] in PROCESSING or S.quiz_mode == "taking"
            with c3, st.container(key=f"del_{d['id']}"):
                if st.button("", icon=":material/delete:", key=f"delbtn_{d['id']}", disabled=busy,
                             help="Đang xử lý hoặc đang làm bài, chưa xoá được" if busy else "Xoá bài này"):
                    S.confirm_delete = d["id"]
                    st.session_state["lib_open"] = True
                    st.rerun()
            st.caption(f"{d['num_slides']} slide · {d['num_accepted']} câu hỏi")
            if S.confirm_delete == d["id"]:
                _confirm_delete(d)
        if ready:
            st.caption(f"Tổng: {sum(d['num_accepted'] for d in ready)} câu hỏi trong ngân hàng")
        if st.session_state.get("delete_err"):
            st.error(st.session_state.pop("delete_err"))


def render(docs: list[dict]) -> None:
    if not S.left_open:
        if st.button("", icon=":material/left_panel_open:", key="open_left", help="Mở thanh tài liệu"):
            S.left_open = True
            st.rerun()
        if st.button("", icon=":material/upload:", key="rail_up", help="Tải lên slide"):
            S.left_open = True
            st.rerun()
        if st.button("", icon=":material/folder:", key="rail_lib", help="Slide đã tải lên"):
            S.left_open = True
            st.rerun()
        return

    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.markdown('<div class="panel-title">Tài liệu</div>', unsafe_allow_html=True)
    if c2.button("", icon=":material/left_panel_close:", key="close_left", help="Thu gọn thanh trái"):
        S.left_open = False
        st.rerun()
    _upload()
    if any(d["status"] in PROCESSING for d in docs):
        _watch_jobs("|".join(f"{d['id']}:{d['status']}" for d in docs))
    else:
        _job_cards(docs)
    _library(docs)
