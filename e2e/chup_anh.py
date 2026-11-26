"""Chụp ảnh giao diện cho báo cáo (mục 3.8) trên dữ liệu thật, ghi PNG vào thư mục /out.

Chạy bằng scripts\\11_chup_anh_bao_cao.bat. Tạo 2 tài khoản tạm (sinh viên, quản trị) đuôi "__e2e@ictu.edu.vn",
cho sinh viên làm vài đề để có hồ sơ hiểu nhầm, hỏi trợ lý 1 câu (gọi OpenAI một lần, vài phần nghìn USD),
chụp ảnh rồi xoá toàn bộ dữ liệu tạm.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from conftest import BASE, TAG, _cleanup  # noqa: E402

sys.path.insert(0, os.environ.get("REPO_DIR", "/repo"))
OUT = os.environ.get("OUT_DIR", "/out")
STUDENT = os.environ.get("DEMO_STUDENT_NAME", "Lê Đình Trung")
ADMIN = os.environ.get("DEMO_ADMIN_NAME", "Vũ Ngọc Thiện")
ASK_ASSISTANT = os.environ.get("ASK_ASSISTANT", "1") == "1"


def make_accounts():
    from app.auth.sessions import create_session
    from app.db import SessionLocal
    from app.models import User
    out = {}
    with SessionLocal() as db:
        _cleanup(db)
        for key, name, admin in (("sv", STUDENT, False), ("gv", ADMIN, True)):
            u = User(code=f"{key}{TAG}", email=f"{key}{TAG}", display_name=name, is_admin=admin)
            db.add(u)
            db.commit()
            out[key] = create_session(db, u, "chup-anh", "127.0.0.1")[0]
    return out


def pick_doc():
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Document, Question
    with SessionLocal() as db:
        return db.execute(select(Document.id, Document.filename)
                          .join(Question, Question.document_id == Document.id)
                          .where(Document.is_active, Document.is_shared, Document.status == "ready",
                                 Question.status == "accepted")
                          .group_by(Document.id).having(func.count(Question.id) >= 20)
                          .order_by(func.count(Question.id).desc())).first()


def shot(page, name, **kw):
    path = os.path.join(OUT, name)
    page.screenshot(path=path, **kw)
    print("  đã chụp", name, flush=True)


def open_doc(page, doc_id, slide):
    """Mở bài ở slide cho trước và chờ ảnh slide tải xong, để khung tạo đề đã sẵn sàng."""
    page.goto(BASE + f"/?doc={doc_id}&slide={slide}")
    img = page.get_by_role("img", name=re.compile(rf"^Slide {slide}"))
    img.wait_for()
    page.wait_for_function("(el) => el.complete && el.naturalWidth > 0", arg=img.element_handle())
    page.wait_for_timeout(800)


def start_quiz(page, button_name="Bắt đầu làm bài"):
    btn = page.get_by_role("button", name=re.compile(button_name))
    btn.wait_for()
    page.wait_for_function("(el) => !el.disabled", arg=btn.element_handle())
    btn.click()
    page.get_by_role("navigation", name="Danh sách câu").wait_for(timeout=60000)
    page.wait_for_timeout(500)


def answer_all(page, wrong_first: int = 6):
    """Làm hết đề: vài câu đầu chọn lần lượt A, B, C, D (thường có câu sai để có chẩn đoán), còn lại chọn A."""
    total = page.get_by_role("navigation", name="Danh sách câu").get_by_role("button").count()
    for i in range(total):
        page.keyboard.press("ABCD"[i % 4] if i < wrong_first else "B")
        page.wait_for_timeout(60)
    page.get_by_role("button", name="Nộp bài").click()
    page.get_by_text("Đã chấm xong").wait_for()


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    doc = pick_doc()
    if not doc:
        sys.exit("Chưa có bài nào trong thư viện chung có từ 20 câu hỏi.")
    doc_id = doc[0]
    acc = make_accounts()
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            try:
                opts = dict(viewport={"width": 1600, "height": 900}, device_scale_factor=2, locale="vi-VN")

                # 1. Trang đăng nhập
                ctx0 = br.new_context(**opts)
                pg = ctx0.new_page()
                pg.goto(BASE + "/login")
                pg.get_by_role("button", name="Đăng nhập bằng Google").wait_for()
                pg.wait_for_timeout(500)
                shot(pg, "gd_1_dang_nhap.png")
                ctx0.close()

                ctx = br.new_context(**opts)
                ctx.add_cookies([{"name": "rq_session", "value": acc["sv"], "url": BASE}])
                pg = ctx.new_page()
                pg.set_default_timeout(30000)

                # Làm trước 2 đề để có lịch sử và hồ sơ hiểu nhầm
                open_doc(pg, doc_id, 1)
                for _ in range(2):
                    start_quiz(pg)
                    answer_all(pg, wrong_first=10)
                    pg.get_by_role("button", name="Làm đề mới").click()
                    pg.wait_for_timeout(800)

                # 2. Không gian học tập + tạo đề (mức Khó)
                open_doc(pg, doc_id, 3)
                pg.get_by_role("radio", name="Khó").click()
                pg.wait_for_timeout(1200)
                shot(pg, "gd_2_hoc_tap.png")

                # 3. Làm bài
                pg.get_by_role("radio", name="Trộn").click()
                start_quiz(pg, "Luyện điểm yếu")
                for k in "ABD":
                    pg.keyboard.press(k)
                    pg.wait_for_timeout(100)
                pg.keyboard.press("f")
                pg.wait_for_timeout(800)
                shot(pg, "gd_3_lam_bai.png")

                # 4–5. Xem lại: câu sai có chẩn đoán, câu trích tô vàng trên slide
                answer_all(pg, wrong_first=10)
                item = pg.locator("article").filter(has_text="Có thể bạn đang nhầm").first
                item.scroll_into_view_if_needed()
                btn = item.get_by_role("button", name=re.compile("Xem trên slide"))
                if btn.count():
                    btn.click()
                    pg.wait_for_timeout(2500)
                item.scroll_into_view_if_needed()
                pg.wait_for_timeout(500)
                shot(pg, "gd_4_xem_lai.png")
                item.screenshot(path=os.path.join(OUT, "gd_5_chan_doan.png"))
                print("  đã chụp gd_5_chan_doan.png", flush=True)

                # 6. Hỏi trợ lý về câu sai (gọi OpenAI một lần)
                if ASK_ASSISTANT:
                    item.get_by_role("button", name="Hỏi trợ lý về câu này").click()
                    tip = pg.get_by_role("button", name=re.compile(r"^Vì sao chọn"))
                    (tip if tip.count() else pg.get_by_role("button", name="Giải thích kỹ hơn bằng ví dụ")).click()
                    try:
                        pg.get_by_text("Nguồn", exact=True).last.wait_for(timeout=120000)
                        pg.wait_for_timeout(1500)
                        shot(pg, "gd_6_tro_ly.png")
                    except Exception as exc:          # OpenAI lỗi / hết hạn mức: bỏ ảnh này, chụp tiếp các ảnh khác
                        print("  BỎ QUA gd_6_tro_ly.png (trợ lý không trả lời):", str(exc).splitlines()[0], flush=True)

                # 7. Kết quả của tôi
                pg.set_viewport_size({"width": 1600, "height": 1250})
                pg.goto(BASE + "/ket-qua")
                pg.get_by_text("Lịch sử làm bài").wait_for()
                pg.wait_for_timeout(1000)
                shot(pg, "gd_7_ket_qua.png")
                ctx.close()

                # 8–9. Quản trị
                ctx2 = br.new_context(**opts)
                ctx2.add_cookies([{"name": "rq_session", "value": acc["gv"], "url": BASE}])
                pg = ctx2.new_page()
                pg.set_default_timeout(30000)
                pg.goto(BASE + "/quan-tri")
                pg.get_by_text("Lượt làm bài 14 ngày gần nhất").wait_for()
                pg.wait_for_timeout(1000)
                shot(pg, "gd_8_quan_tri.png")
                pg.goto(BASE + "/quan-tri?tab=bai-giang")
                pg.get_by_role("table").wait_for()
                name = re.sub(r"\.(pptx|pdf)$", "", doc[1], flags=re.I).replace("_", " ").strip()
                pg.get_by_role("button", name=name, exact=True).click()
                pg.get_by_text(re.compile("Ngân hàng câu hỏi ·")).wait_for()
                pg.wait_for_timeout(1000)
                shot(pg, "gd_9_ngan_hang.png")
                ctx2.close()
            except Exception:
                for c in br.contexts:
                    for pg_ in c.pages:
                        try:
                            pg_.screenshot(path=os.path.join(OUT, "_loi_chup_anh.png"))
                        except Exception:
                            pass
                raise
            br.close()
    finally:
        from app.db import SessionLocal
        with SessionLocal() as db:
            _cleanup(db)
        print("Đã xoá dữ liệu tạm.", flush=True)


if __name__ == "__main__":
    main()
