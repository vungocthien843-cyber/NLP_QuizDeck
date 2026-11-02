"""Màu, font và các mảnh HTML dùng chung (tông xanh ICTU như bản thiết kế đã duyệt)."""
import base64
import html
from functools import lru_cache
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent.parent / "assets"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--brand:#0072B1;--brand-600:#0A84C6;--brand-400:#4FB0E3;--brand-100:#DCEFFB;--brand-50:#EEF7FD;
  --bg:#F3F8FC;--ink:#0E2A3D;--ink-2:#4A6478;--ink-3:#7F96A8;--line:#D9E8F2;--line-2:#C3DAEA;
  --ok:#15803D;--ok-bg:#E8F6EC;--bad:#C2410C;--bad-bg:#FDEEE6;--warn:#B45309;--warn-bg:#FEF4E2;--hl:#FFF1A8;
  --mono:'JetBrains Mono',ui-monospace,monospace}
html,body,[class*="css"],.stApp,.stMarkdown,button,input,textarea,select{font-family:'Be Vietnam Pro',system-ui,sans-serif!important}
.stApp{background:var(--bg)}
header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],footer,
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none!important}
.block-container{padding:0 1rem 1rem!important;max-width:100%!important}
/* thanh trên */
.topbar{display:flex;align-items:center;gap:14px;padding:10px 6px 10px;margin:0 -1rem 12px;padding-left:1.2rem;padding-right:1.2rem;
  background:#fff;border-bottom:1px solid var(--line)}
.topbar img{width:42px;height:42px;border-radius:50%}
.topbar .name{font-weight:600;font-size:16px;line-height:1.2;color:var(--ink)}
.topbar .sub{font-size:12px;color:var(--ink-3)}
.topbar .sp{flex:1}
.topbar .course{display:flex;align-items:center;gap:8px;padding:5px 12px;border:1px solid var(--line);border-radius:999px;
  background:var(--brand-50);color:var(--brand);font-weight:500;font-size:13px}
.topbar .course i{width:7px;height:7px;border-radius:50%;background:var(--brand-400);display:inline-block}
/* 3 cột: mỗi cột là một panel trắng */
.st-key-left_panel,.st-key-right_panel,.st-key-center_panel>div:first-child{}
.st-key-left_panel,.st-key-right_panel{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px!important}
.st-key-center_panel{background-image:radial-gradient(circle,#D3E4F0 1px,transparent 1.2px);background-size:22px 22px;border-radius:14px;padding:4px}
.panel-title{font-size:13px;font-weight:600;color:var(--ink-2);margin:2px 0 6px}
.sec-title{font-weight:600;font-size:13.5px;color:var(--ink);display:flex;align-items:center;gap:6px;margin:4px 0 6px}
/* nút */
.stButton>button,.stDownloadButton>button{border-radius:8px;border:1px solid var(--line-2);font-weight:500}
.stButton>button[kind="primary"]{background:var(--brand);border-color:var(--brand)}
.stButton>button[kind="primary"]:hover{background:var(--brand-600);border-color:var(--brand-600)}
.stButton>button:hover{border-color:var(--brand-400);color:var(--brand)}
.stButton>button[kind="primary"]:hover{color:#fff}
.stButton>button[kind="primary"]:disabled{background:var(--brand-100);border-color:var(--brand-100);color:var(--ink-3)}
[data-testid="stFileUploaderDropzone"]{background:var(--brand-50);border:1.5px dashed var(--brand-400);border-radius:10px}
[data-testid="stExpander"] details{border:1px solid var(--line);border-radius:12px;background:#fff}
/* tài liệu */
.doc-row{display:flex;gap:10px;align-items:center;font-size:13px}
.pill{font-size:11px;padding:2px 8px;border-radius:99px;font-weight:500;white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.run{background:var(--warn-bg);color:var(--warn)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
[class*="st-key-del_"] .stButton button{min-height:32px;padding:0 6px;border-color:transparent;background:transparent;color:var(--ink-3)}
[class*="st-key-del_"] .stButton button:hover{color:var(--bad);border-color:var(--bad-bg);background:var(--bad-bg)}
.st-key-confirm_box{padding:10px;border:1px solid #F3B999;background:var(--bad-bg);border-radius:10px;gap:8px}
.confirm{font-size:12.5px;color:var(--ink-2)}
.confirm b{display:block;font-size:13.5px;color:var(--bad);margin-bottom:2px}
.st-key-confirm_box [data-testid="stMarkdownContainer"],.st-key-confirm_box .stMarkdown>div>div{margin-bottom:0!important}
.st-key-confirm_box .stButton button{min-height:36px;background:#fff;color:var(--ink)}
.st-key-confirm_box .stButton button[kind="primary"]{background:var(--bad);border-color:var(--bad);color:#fff}
.st-key-confirm_box .stButton button[kind="primary"]:hover{background:#9A3412;border-color:#9A3412;color:#fff}
.st-key-confirm_box .stButton button[kind="primary"] p{color:#fff}
.job{padding:10px;border-radius:10px;background:var(--bg);font-size:12.5px;margin:6px 0}
.job .n{display:flex;justify-content:space-between;font-weight:500;gap:8px}
.steps{display:flex;gap:4px;margin-top:4px;color:var(--ink-3);font-size:11.5px;flex-wrap:wrap}
.steps .done{color:var(--ok)}.steps .now{color:var(--brand);font-weight:500}
/* slide */
.crumb{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:4px 0 8px}
.crumb h1{font-size:19px!important;font-weight:600!important;margin:0!important;padding:0!important;color:var(--ink)}
.tag{font-family:var(--mono);font-size:12px;color:var(--brand);background:var(--brand-50);border:1px solid var(--brand-100);padding:2px 8px;border-radius:6px}
.slide-frame{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px}
.slide-frame img{width:100%;border-radius:8px;border:1px solid var(--line);display:block}
.refbar{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;background:var(--warn-bg);color:var(--warn);font-size:13px;font-weight:500;margin-bottom:8px}
.notes{padding:10px 14px;border-radius:10px;background:#fff;border:1px solid var(--line);font-size:13px;color:var(--ink-2);margin-top:8px}
.notes b{color:var(--ink)}
.lock-wrap{position:relative;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:#fff}
.lock-wrap img{width:100%;display:block;filter:blur(9px);opacity:.45;transform:scale(1.02)}
.lock-card{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.lock-card div{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 22px;text-align:center;max-width:330px;
  box-shadow:0 12px 40px rgba(14,42,61,.12);font-size:13px;color:var(--ink-2)}
.lock-card b{display:block;font-size:15px;color:var(--ink);margin-bottom:4px}
.empty{background:#fff;border:1px dashed var(--line-2);border-radius:14px;padding:48px 24px;text-align:center;color:var(--ink-2)}
.empty b{display:block;font-size:17px;color:var(--ink);margin-bottom:6px}
/* khung slide cuộn liên tục (iframe) */
.st-key-slide_view iframe{border:0}
/* khung cố định theo màn hình: trang không cuộn, mỗi cột tự cuộn bên trong */
:root{--panel-h:calc(100vh - 106px)}
@media (min-height:560px){
  html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],section.main{overflow:hidden!important}
  .st-key-left_panel,.st-key-right_panel{height:var(--panel-h)!important;flex:0 0 auto!important;overflow-y:auto;overflow-x:hidden;flex-wrap:nowrap}
  .st-key-center_panel{height:var(--panel-h)!important;flex:0 0 auto!important;overflow:hidden;flex-wrap:nowrap}
  .st-key-center_panel>div{flex:none}
  .st-key-center_panel>div:has(.st-key-slide_view){flex:1 1 0!important;min-height:0}
  .st-key-slide_view{height:100%!important;flex:1 1 auto!important}
  .st-key-slide_view>[data-testid="stElementContainer"]{flex:1 1 0!important;min-height:0;height:auto!important}
  .st-key-slide_view iframe{height:100%!important;width:100%}
  .st-key-chat_box{height:calc(var(--panel-h) - 235px)!important;max-height:none!important;flex:0 0 auto!important}
  .st-key-review_box{height:calc(var(--panel-h) - 300px)!important;max-height:none!important;flex:0 0 auto!important}
}
@media (max-height:559px){.st-key-slide_view iframe{height:480px!important}}
/* chat */
.st-key-chat_box{padding-right:4px}
[class*="st-key-msgu_"]{margin:6px 0 10px 18%;padding:10px 14px;background:var(--brand);border-radius:14px 14px 4px 14px;width:auto!important}
[class*="st-key-msg"] [data-testid="stMarkdownContainer"],[class*="st-key-msg"] .stMarkdown>div>div{margin-bottom:0!important}
[class*="st-key-msg"] p{margin:0 0 .55em}
[class*="st-key-msg"] p:last-child{margin-bottom:0}
[class*="st-key-msgu_"] p,[class*="st-key-msgu_"] li{color:#fff;font-size:14px}
[class*="st-key-msgu_"] .att-in-msg{background:rgba(255,255,255,.14);border-left-color:#fff;color:#EAF4FB}
[class*="st-key-msga_"]{margin:6px 6% 12px 0;padding:10px 14px 12px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 14px 14px;gap:.4rem}
[class*="st-key-msga_"] p,[class*="st-key-msga_"] li{font-size:14px;line-height:1.6;color:var(--ink)}
.who{font-size:11.5px;font-weight:600;color:var(--brand);letter-spacing:.2px;display:flex;align-items:center;gap:6px}
.who::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--brand)}
.msg-err{font-size:13px;color:var(--bad);background:var(--bad-bg);border-radius:8px;padding:8px 10px}
.src-head{font-size:11px;font-weight:600;color:var(--ink-3);text-transform:uppercase;letter-spacing:.6px;margin-top:4px;
  border-top:1px solid var(--line);padding-top:8px}
[class*="st-key-cites_"]{gap:4px}
[class*="st-key-cites_"] .stButton button{min-height:30px;padding:3px 10px;font-size:12.5px;justify-content:flex-start;
  background:var(--brand-50);border:1px solid var(--brand-100);color:var(--brand);border-radius:7px}
[class*="st-key-cites_"] .stButton button *,.st-key-suggest .stButton>button *,.st-key-tips .stButton>button *{justify-content:flex-start!important;text-align:left!important}
[class*="st-key-cites_"] .stButton button>div{width:100%}
[class*="st-key-cites_"] .stButton button p{font-size:12.5px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st-key-chat_box{min-height:240px}
.st-key-chat_box iframe{display:none}
.chat-empty{padding:18px 4px 10px;font-size:13px;color:var(--ink-2)}
.chat-empty b{display:block;font-size:15px;color:var(--ink);margin-bottom:4px}
.st-key-suggest .stButton>button,.st-key-tips .stButton>button{justify-content:flex-start;font-size:13px;min-height:36px;
  border-radius:10px;background:#fff;color:var(--ink-2)}
.st-key-suggest .stButton>button p,.st-key-tips .stButton>button p{font-size:13px;text-align:left}
.st-key-suggest .stButton>button>div,.st-key-tips .stButton>button>div{justify-content:flex-start;width:100%}
.st-key-tips .stButton>button{min-height:32px}
[data-testid="stChatInput"]{border-radius:12px}
.attach{display:flex;gap:10px;padding:10px;border:1px solid var(--brand-100);background:var(--brand-50);border-radius:10px;font-size:12.5px}
.attach b{display:block;font-size:11.5px;color:var(--brand)}
.attach .ans{font-size:11.5px;color:var(--ink-2);margin-top:2px}
.att-in-msg{border-left:3px solid var(--brand-400);padding:2px 8px;margin-bottom:6px;font-size:12px;color:var(--ink-2);background:#fff;border-radius:4px}
.scope{font-size:12px;color:var(--ink-3);margin-bottom:4px}
.locked{padding:12px;border-radius:10px;background:var(--bg);font-size:13px;color:var(--ink-2)}
/* tạo đề */
.avail{display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:10px;background:var(--bg);font-size:12.5px;color:var(--ink-2);margin:6px 0}
.avail b{font-size:20px;color:var(--ink);font-weight:600}
.avail .alloc{margin-left:auto;text-align:right;font-size:11.5px}
.hint{font-size:11.5px;color:var(--ink-3)}
.field-label{font-size:14px;color:var(--ink);margin:2px 0 2px}
.st-key-pick_docs{gap:2px;padding:6px 10px;border:1px solid var(--line);border-radius:10px;max-height:240px;overflow-y:auto;flex-wrap:nowrap}
.st-key-pick_docs [data-testid="stCheckbox"] label p{font-size:13.5px}
/* làm bài */
.qtop{display:flex;align-items:center;gap:10px;font-size:13px}
.qtop b{flex:1;font-size:14px}
.timer{font-family:var(--mono);color:var(--brand);font-weight:500}
.timer.low{color:var(--bad)}
.bar{height:6px;border-radius:99px;background:var(--brand-100);overflow:hidden;margin:6px 0 8px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--brand-400),var(--brand));border-radius:99px}
.qn{font-family:var(--mono);font-size:12px;color:var(--brand);display:flex;gap:8px;align-items:center;margin:4px 0}
.lvl{font-family:'Be Vietnam Pro',sans-serif;font-size:11px;padding:1px 8px;border-radius:99px;background:var(--brand-50);color:var(--brand);border:1px solid var(--brand-100)}
.stem{font-weight:500;font-size:15px;margin:2px 0 10px;color:var(--ink)}
.st-key-options .stButton>button{justify-content:flex-start;text-align:left;padding:10px 12px;min-height:44px;white-space:normal}
.st-key-options .stButton>button>div,.st-key-options .stButton>button [data-testid="stMarkdownContainer"]{justify-content:flex-start;text-align:left;width:100%}
.st-key-options .stButton>button p{text-align:left}
.st-key-palette .stButton>button{padding:0;min-height:30px;height:30px;font-family:var(--mono);font-size:12px}
/* kết quả */
.score{display:flex;gap:16px;align-items:center}
.ring{width:84px;height:84px;border-radius:50%;display:grid;place-items:center;flex:none}
.ring div{width:66px;height:66px;border-radius:50%;background:#fff;display:grid;place-items:center;text-align:center;line-height:1.05}
.ring b{font-size:20px;font-weight:600;color:var(--brand)} .ring small{font-size:10px;color:var(--ink-3)}
.stat{padding:3px 10px;border-radius:8px;background:var(--bg);font-size:12px;color:var(--ink-2);margin-right:4px}
.stat.ok b{color:var(--ok)}.stat.bad b{color:var(--bad)}
.res{font-family:'Be Vietnam Pro',sans-serif;font-size:11px;font-weight:600;padding:1px 8px;border-radius:99px}
.res.ok{background:var(--ok-bg);color:var(--ok)}.res.bad{background:var(--bad-bg);color:var(--bad)}
.ropt{display:flex;gap:8px;align-items:center;padding:7px 10px;border:1px solid var(--line);border-radius:9px;margin-bottom:5px;font-size:13px;background:#fff}
.ropt .L{width:22px;height:22px;border-radius:6px;border:1px solid var(--line-2);display:grid;place-items:center;font-family:var(--mono);font-size:11px;flex:none}
.ropt .why{margin-left:auto;font-size:11px;font-weight:600;white-space:nowrap}
.ropt.right{border-color:#9ED7B0;background:var(--ok-bg)}.ropt.right .L{background:var(--ok);border-color:var(--ok);color:#fff}.ropt.right .why{color:var(--ok)}
.ropt.wrong{border-color:#F3B999;background:var(--bad-bg)}.ropt.wrong .L{background:var(--bad);border-color:var(--bad);color:#fff}.ropt.wrong .why{color:var(--bad)}
.rat{font-size:12px;color:var(--ink-2);margin:-1px 0 6px 40px}
.expl{margin-top:6px;font-size:13px;padding:8px 10px;border-radius:9px;background:var(--bg)}
.evid{margin-top:8px;border:1px solid var(--brand-100);border-radius:10px;overflow:hidden}
.evid .eh{display:flex;align-items:center;gap:6px;padding:6px 10px;background:var(--brand-50);font-size:12px;font-weight:600;color:var(--brand)}
.evid .eh .ver{margin-left:auto;color:var(--ok);font-weight:500;font-size:11.5px}
.evid .eh .ver.no{color:var(--warn)}
.evid .eb{padding:10px}
.quote{font-size:13px;border-left:3px solid var(--brand-400);padding:1px 0 1px 10px;margin:0 0 6px}
.quote mark{background:var(--hl);border-radius:3px;padding:0 2px}
.srcline{font-size:11.5px;color:var(--ink-3);font-family:var(--mono)}
.viewing-tag{font-size:11px;color:var(--brand);font-weight:600}
</style>
"""


@lru_cache
def _logo_b64() -> str:
    p = ASSETS / "logo_ictu.jpg"
    return base64.b64encode(p.read_bytes()).decode() if p.is_file() else ""


def esc(s) -> str:
    return html.escape(str(s or ""))


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header() -> None:
    logo = f'<img src="data:image/jpeg;base64,{_logo_b64()}" alt="Logo ICTU">' if _logo_b64() else ""
    st.markdown(f'<div class="topbar">{logo}<div class="name">ICTU · Trợ lý học tập</div></div>',
                unsafe_allow_html=True)


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)
