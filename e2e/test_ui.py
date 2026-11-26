"""Các luồng chính của giao diện mới. Xem e2e/conftest.py để biết cách chạy và dữ liệu thử."""
import re

from conftest import BASE


def title_of(filename: str) -> str:
    return re.sub(r"\.(pptx|pdf)$", "", filename, flags=re.I).replace("_", " ").strip()


def test_login_page_and_google_redirect(page_as):
    page = page_as(None)
    page.goto(BASE + "/ket-qua")
    page.wait_for_url(re.compile(r"/login\?next="))
    seen = {}
    page.on("request", lambda r: seen.setdefault("url", r.url) if "accounts.google.com" in r.url else None)
    page.get_by_role("button", name="Đăng nhập bằng Google").click()
    page.wait_for_timeout(2000)
    assert "hd=ictu.edu.vn" in seen.get("url", "") and "code_challenge_method=S256" in seen.get("url", "")
    page.goto(BASE + "/login?error=domain")
    assert "@ictu.edu.vn" in page.get_by_role("alert").inner_text()


def test_forged_session_rejected(browser):
    ctx = browser.new_context()
    ctx.add_cookies([{"name": "rq_session", "value": "gia-mao", "url": BASE}])
    page = ctx.new_page()
    page.goto(BASE + "/")
    page.wait_for_url(re.compile(r"/login"))
    ctx.close()


def test_study_quiz_review_flow(page_as, quiz_doc):
    page = page_as("sv")
    page.goto(BASE + f"/?doc={quiz_doc['id']}&slide=1")
    img = page.get_by_role("img", name=re.compile(r"^Slide 1"))
    img.wait_for()
    page.wait_for_function("(el) => el.complete && el.naturalWidth > 0", arg=img.element_handle())
    page.keyboard.press("ArrowRight")
    page.wait_for_url(re.compile(r"slide=2"))
    # tạo đề 10 câu từ bài đang xem
    page.get_by_role("button", name=re.compile("Bắt đầu làm bài")).click()
    page.get_by_text("Câu 1/10").wait_for()
    assert page.get_by_text("Slide tạm ẩn khi làm bài").is_visible()
    page.get_by_role("tab", name=re.compile("Trợ lý")).click()
    assert page.get_by_text("Trợ lý tạm khóa").is_visible()
    page.get_by_role("tab", name=re.compile("Trắc nghiệm")).click()
    for i in range(5):
        page.keyboard.press("ABCD"[i % 4])
        page.wait_for_timeout(80)
    page.reload()
    page.get_by_text("Câu 6/10").wait_for()                       # tải lại trang không mất bài
    for i in range(5):
        page.keyboard.press("ABCD"[i % 4])
        page.wait_for_timeout(80)
    page.get_by_role("button", name="Nộp bài").click()
    page.get_by_text("Đã chấm xong").wait_for()
    page.get_by_role("radio", name=re.compile("Tất cả")).click()
    btn = page.get_by_role("button", name="Xem trên slide").first
    if btn.count():
        btn.click()
        assert "slide=" in page.url
    page.get_by_role("button", name="Hỏi trợ lý về câu này").first.click()
    assert page.get_by_text(re.compile("Đính kèm · Câu")).is_visible()
    assert not page.js_errors, page.js_errors


def test_results_page(page_as, quiz_doc):
    page = page_as("sv")
    page.goto(BASE + "/ket-qua")
    page.get_by_text("Kết quả của tôi").first.wait_for()
    page.get_by_text("Lịch sử làm bài").wait_for()
    assert page.locator("tbody tr").count() >= 1
    page.get_by_role("button", name=re.compile("Xem lại")).first.click()
    page.get_by_text("Đã chấm xong").wait_for()
    assert not page.js_errors, page.js_errors


def test_admin_pages(page_as, quiz_doc):
    page = page_as("gv")
    page.goto(BASE + "/quan-tri")
    page.get_by_text("Lượt làm bài 14 ngày gần nhất").wait_for()
    page.get_by_role("tab", name="Bài giảng").click()
    page.get_by_role("button", name=title_of(quiz_doc["filename"]), exact=True).click()
    page.get_by_text(re.compile("Ngân hàng câu hỏi ·")).wait_for()
    page.get_by_role("button", name="Danh sách bài giảng").click()
    page.get_by_role("tab", name="Sinh viên").click()
    page.get_by_text("sv__e2e@ictu.edu.vn").wait_for()
    assert not page.js_errors, page.js_errors


def test_student_cannot_open_admin(page_as):
    page = page_as("sv")
    page.goto(BASE + "/quan-tri")
    page.wait_for_timeout(1500)
    assert not page.url.endswith("/quan-tri")
    assert page.get_by_role("link", name="Quản trị").count() == 0
