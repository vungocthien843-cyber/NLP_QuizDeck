"""Cột giữa: xem toàn bộ slide, cuộn dọc như trình chiếu; tô vàng câu trích khi đối chiếu; làm mờ khi làm bài.

Khung slide là một iframe (components.html) để cuộn độc lập với trang và tự cuộn tới slide được chọn.
Ảnh tải thẳng từ API bằng trình duyệt (loading="lazy"), nên chỉ slide đang cuộn tới mới được tải.
"""
import json

import streamlit as st
import streamlit.components.v1 as components

import api_client as api
from views.left import call
from views.state import TAB_CHAT, TAB_QUIZ, S, clear_highlight, go, open_right
from views.theme import esc, html_block

VIEWER_HEIGHT = 720     # chiều cao mặc định; CSS trong theme.py co giãn theo cửa sổ


@st.cache_data(ttl=60, show_spinner=False)
def _slides(doc_id: int, version: str) -> dict:
    return api.list_slides(doc_id)


VIEWER_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--brand:#0072B1;--brand-50:#EEF7FD;--brand-100:#DCEFFB;--bg:#F3F8FC;--ink:#0E2A3D;--ink-2:#4A6478;--ink-3:#7F96A8;--line:#D9E8F2;--hl:#FFE46B}
*{box-sizing:border-box}html,body{margin:0;height:100%;font-family:'Be Vietnam Pro',system-ui,sans-serif;color:var(--ink);background:#fff}
.wrap{height:100vh;display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg)}
.bar{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#fff;border-bottom:1px solid var(--line);flex:none}
.bar button{height:32px;min-width:34px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer;font:inherit;color:var(--ink)}
.bar button:hover{border-color:var(--brand);color:var(--brand)}
.bar .pos{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--ink-2);min-width:70px;text-align:center}
.bar select{flex:1;min-width:0;height:32px;border:1px solid var(--line);border-radius:8px;padding:0 8px;font:inherit;font-size:13px;color:var(--ink);background:#fff}
.scroll{flex:1;overflow-y:auto;padding:16px 18px 40px;scroll-behavior:smooth}
.slide{max-width:1100px;margin:0 auto 18px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px;scroll-margin-top:12px}
.slide.target{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-100)}
.slide img{display:block;width:100%;height:auto;border-radius:6px;background:#f6f9fc}
.meta{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink-3);padding:6px 4px 0}
.meta b{font-family:'JetBrains Mono',monospace;font-weight:500;color:var(--brand)}
.notes{margin:6px 4px 2px;padding:8px 10px;border-radius:8px;background:var(--bg);font-size:12.5px;color:var(--ink-2);cursor:pointer;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.notes.open{display:block}
.notes strong{color:var(--ink)}
.locked .scroll{filter:blur(9px);opacity:.45;pointer-events:none;user-select:none;overflow:hidden}
.lock{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.lock div{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 22px;text-align:center;max-width:340px;
  box-shadow:0 12px 40px rgba(14,42,61,.12);font-size:13px;color:var(--ink-2)}
.lock b{display:block;font-size:15px;color:var(--ink);margin-bottom:4px}
</style></head><body>
<div class="wrap __LOCKED__" style="position:relative">
  <div class="bar">
    <button id="prev" title="Slide trước">‹</button><span class="pos" id="pos">1 / __N__</span><button id="next" title="Slide sau">›</button>
    <select id="jump" title="Đi tới slide"></select>
  </div>
  <div class="scroll" id="scroll"></div>
  __LOCK__
</div>
<script>
const D = __DATA__;
const sc = document.getElementById('scroll'), jump = document.getElementById('jump'), pos = document.getElementById('pos');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
D.slides.forEach(s => {
  const el = document.createElement('section');
  el.className = 'slide' + (s.slide_no === D.target ? ' target' : ''); el.id = 's' + s.slide_no;
  const size = s.width && s.height ? ` width="${s.width}" height="${s.height}"` : ' style="aspect-ratio:16/9"';
  el.innerHTML = `<img src="${esc(s.src)}" alt="Slide ${s.slide_no}" loading="lazy"${size}>` +
    `<div class="meta"><span>${esc(s.title || '')}</span><b>${s.slide_no} / ${D.slides.length}</b></div>` +
    (s.notes ? `<div class="notes" title="Bấm để xem đầy đủ" onclick="this.classList.toggle('open')"><strong>Ghi chú của giảng viên:</strong> ${esc(s.notes)}</div>` : '');
  sc.appendChild(el);
  const o = document.createElement('option'); o.value = s.slide_no; o.textContent = s.slide_no + ' · ' + (s.title || 'Slide ' + s.slide_no);
  jump.appendChild(o);
});
const els = [...document.querySelectorAll('.slide')];
const topOf = n => els[n - 1].offsetTop - sc.offsetTop - 10;      // vị trí của slide n trong vùng cuộn
let cur = D.target, navUntil = 0;   // trong lúc tự cuộn tới slide đích thì không cập nhật theo vị trí cuộn
const show = n => { cur = n; pos.textContent = n + ' / ' + D.slides.length; jump.value = n; };
const goTo = (n, smooth = true) => { n = Math.max(1, Math.min(D.slides.length, n)); navUntil = Date.now() + 1200;
  sc.scrollTo({top: topOf(n), behavior: smooth ? 'smooth' : 'auto'}); show(n); };
document.getElementById('prev').onclick = () => goTo(cur - 1);
document.getElementById('next').onclick = () => goTo(cur + 1);
jump.onchange = () => goTo(+jump.value);
document.addEventListener('keydown', e => { if (e.key === 'ArrowDown' || e.key === 'PageDown') { e.preventDefault(); goTo(cur + 1); }
  if (e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); goTo(cur - 1); } });
let ticking = false;
sc.addEventListener('scroll', () => { if (ticking || Date.now() < navUntil) return; ticking = true;
  requestAnimationFrame(() => { ticking = false; const y = sc.scrollTop + 40;
    let n = 1; for (let i = 1; i <= els.length; i++) { if (topOf(i) <= y) n = i; else break; }
    show(n); }); });
requestAnimationFrame(() => goTo(D.target, false));
</script></body></html>"""

LOCK_HTML = ('<div class="lock"><div><b>Đang làm bài trắc nghiệm</b>Slide tạm ẩn trong lúc làm bài. '
             'Nộp bài xong slide sẽ hiện lại để bạn đối chiếu đáp án.</div></div>')


def _viewer_html(doc_id: int, info: dict, target: int, highlight: str | None, locked: bool, seq: int) -> str:
    slides = [{**s, "src": api.slide_url(doc_id, s["slide_no"], highlight if s["slide_no"] == target else None)}
              for s in info["slides"]]
    data = json.dumps({"slides": slides, "target": target, "seq": seq}, ensure_ascii=False).replace("</", "<\\/")
    return (VIEWER_TEMPLATE.replace("__DATA__", data).replace("__N__", str(len(slides)))
            .replace("__LOCKED__", "locked" if locked else "").replace("__LOCK__", LOCK_HTML if locked else ""))


def render(docs: list[dict]) -> None:
    viewable = [d for d in docs if d["num_slides"] > 0]
    if not viewable:
        html_block('<div class="empty"><b>Chưa có slide để học</b>Tải file .pptx hoặc .pdf ở thanh bên trái. '
                   'Hệ thống sẽ hiện slide ở đây và tự sinh câu hỏi trắc nghiệm.</div>')
        return
    if S.doc_id not in {d["id"] for d in viewable}:
        go(viewable[0]["id"], 1)
    doc = next(d for d in viewable if d["id"] == S.doc_id)
    info, err = call(_slides, doc["id"], f'{doc["filename"]}|{doc["num_slides"]}')
    if err:
        st.error(err)
        return
    n = info["num_slides"]
    S.slide = min(max(1, S.slide), n)
    quizzing = S.quiz_mode == "taking"

    name = doc["filename"].rsplit(".", 1)[0]
    c1, c2, c3 = st.columns([4, 0.55, 1.5], vertical_alignment="center")
    c1.markdown(f'<div class="crumb"><h1>{esc(name)}</h1><span class="tag">{n} slide</span></div>',
                unsafe_allow_html=True)
    if c2.button("", icon=":material/chat:", use_container_width=True, disabled=quizzing, key="ask_btn",
                 help="Hỏi trợ lý về bài này"):
        open_right(TAB_CHAT)
        st.rerun()
    if c3.button("Trắc nghiệm", icon=":material/quiz:", type="primary", use_container_width=True,
                 disabled=quizzing, key="quiz_btn"):
        open_right(TAB_QUIZ)
        st.rerun()

    if S.highlight and not quizzing:
        r1, r2 = st.columns([6, 1], vertical_alignment="center")
        what = "câu được trích dẫn" if S.viewing is None else "căn cứ cho đáp án đúng của câu đang xem lại"
        r1.markdown(f'<div class="refbar">Slide {S.slide}: phần tô vàng là {what}.</div>', unsafe_allow_html=True)
        if r2.button("Bỏ tô", key="clear_hl", use_container_width=True):
            clear_highlight()
            st.rerun()

    with st.container(key="slide_view"):
        components.html(_viewer_html(doc["id"], info, S.slide, None if quizzing else S.highlight, quizzing,
                                     S.get("jump_seq", 0)), height=VIEWER_HEIGHT)
