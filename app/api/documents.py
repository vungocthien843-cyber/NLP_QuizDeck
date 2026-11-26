"""Upload slide, danh sách bài đã tải, xem slide (có tô câu trích), sinh thêm câu hỏi (mục 5, 7)."""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import slides
from app.auth.access import can_edit, get_editable, get_visible, unrestricted, visible_clause
from app.auth.deps import require_user
from app.config import get_settings
from app.db import get_db
from app.generation.bank_builder import run_generate_more
from app.ingestion.pipeline import run_pipeline
from app.models import Chunk, Document, Question, User
from app.schemas import DocumentOut, DocumentPatch, GenerateMoreIn, QuotaOut, SlideInfo, SlidesOut

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_user)])

ALLOWED_EXT = {".pdf", ".pptx"}
PROCESSING = {"uploaded", "parsing", "embedding", "generating"}
MAX_GENERATE_STUDENT = 30


def _to_out(db: Session, doc: Document, user: User | None = None) -> DocumentOut:
    num_chunks = db.scalar(select(func.count()).where(Chunk.document_id == doc.id, Chunk.is_active))
    counts = dict(
        db.execute(
            select(Question.status, func.count()).where(Question.document_id == doc.id).group_by(Question.status)
        ).all()
    )
    return DocumentOut(
        id=doc.id, filename=doc.filename, session_no=doc.session_no, status=doc.status, error=doc.error,
        num_chunks=num_chunks or 0, num_accepted=counts.get("accepted", 0), num_rejected=counts.get("rejected", 0),
        num_slides=slides.slide_count(doc.id),
        is_shared=doc.is_shared, is_mine=user is not None and doc.owner_user_id == user.id,
        can_edit=can_edit(user, doc),
        owner_email=(db.get(User, doc.owner_user_id).email if doc.owner_user_id and user is not None and user.is_admin
                     and db.get(User, doc.owner_user_id) else None),
    )


def _own_docs(db: Session, user: User):
    return select(Document).where(Document.is_active.is_(True), Document.owner_user_id == user.id,
                                  Document.is_shared.is_(False))


def _quota(db: Session, user: User | None) -> QuotaOut:
    s = get_settings()
    if unrestricted(user):
        return QuotaOut(unlimited=True, max_docs=0, used_docs=0, max_upload_mb=s.max_upload_mb)
    used = db.scalar(select(func.count()).select_from(_own_docs(db, user).subquery()))
    return QuotaOut(unlimited=False, max_docs=s.student_max_docs, used_docs=used or 0, max_upload_mb=s.max_upload_mb)


def _check_busy(db: Session, user: User | None) -> None:
    """Sinh viên chỉ được chạy student_max_processing việc tốn LLM cùng lúc (tải lên / sinh thêm câu hỏi)."""
    if unrestricted(user):
        return
    busy = db.scalar(select(func.count()).select_from(
        _own_docs(db, user).where(Document.status.in_(PROCESSING)).subquery()))
    if (busy or 0) >= get_settings().student_max_processing:
        raise HTTPException(429, "Bạn đang có bài chưa xử lý xong. Đợi bài đó xong rồi tải tiếp.")


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> list[DocumentOut]:
    """Bài người dùng được xem (thư viện chung + slide riêng của mình), theo thứ tự thời gian tải."""
    docs = db.scalars(select(Document).where(visible_clause(user)).order_by(Document.created_at))
    return [_to_out(db, d, user) for d in docs]


@router.get("/quota", response_model=QuotaOut)
def get_quota(db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> QuotaOut:
    return _quota(db, user)


@router.post("", response_model=DocumentOut)
def upload_document(
    background: BackgroundTasks,
    file: UploadFile,
    session_no: int | None = Form(None),
    shared: bool | None = Form(None, description="Chỉ quản trị viên: true = đưa vào thư viện chung (mặc định)"),
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
) -> DocumentOut:
    """Quản trị viên tải lên → thư viện chung (trừ khi shared=false). Sinh viên tải lên → slide riêng, có hạn mức."""
    settings = get_settings()
    if not unrestricted(user):
        q = _quota(db, user)
        if q.used_docs >= q.max_docs:
            raise HTTPException(429, f"Bạn đã dùng hết hạn mức {q.max_docs} bài. Xóa bớt bài cũ để tải bài mới.")
        _check_busy(db, user)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Chỉ hỗ trợ {', '.join(sorted(ALLOWED_EXT))}")
    if file.size and file.size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File vượt quá {settings.max_upload_mb} MB")

    dest = settings.upload_dir / f"{uuid.uuid4().hex}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    is_shared = True if user is None else (user.is_admin and shared is not False)
    doc = Document(filename=file.filename, file_path=str(dest), session_no=session_no, source_type="slide",
                   owner_user_id=user.id if user else None, is_shared=is_shared)
    db.add(doc)
    db.commit()
    background.add_task(run_pipeline, doc.id)
    return _to_out(db, doc, user)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db),
                 user: User | None = Depends(require_user)) -> DocumentOut:
    return _to_out(db, get_visible(db, user, document_id), user)


@router.patch("/{document_id}", response_model=DocumentOut)
def patch_document(document_id: int, body: DocumentPatch, db: Session = Depends(get_db),
                   user: User | None = Depends(require_user)) -> DocumentOut:
    doc = get_editable(db, user, document_id)
    if body.is_shared is not None and body.is_shared != doc.is_shared:
        if not unrestricted(user):
            raise HTTPException(403, "Chỉ quản trị viên được đưa bài vào hoặc ra khỏi thư viện chung")
        doc.is_shared = body.is_shared
    if "session_no" in body.model_fields_set:
        doc.session_no = body.session_no
    db.commit()
    return _to_out(db, doc, user)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db),
                    user: User | None = Depends(require_user)) -> Response:
    """Xoá ẩn: tài liệu và các chunk của nó thành is_active = false nên không còn hiện trong thư viện,
    không được dùng khi tạo đề (quiz_sampler lọc Document.is_active) và khi trợ lý truy hồi (hybrid lọc
    c.is_active). Câu hỏi, đề và bài làm cũ vẫn giữ trong DB để điểm các lần làm trước không đổi.
    Ảnh slide và file gốc trên ổ đĩa được xoá cho nhẹ máy."""
    doc = get_editable(db, user, document_id)
    if doc.status in PROCESSING:
        raise HTTPException(409, "Bài đang được xử lý, đợi xử lý xong rồi xoá.")
    doc.is_active = False
    db.execute(update(Chunk).where(Chunk.document_id == doc.id).values(is_active=False))
    db.commit()
    shutil.rmtree(slides.render_dir(doc.id), ignore_errors=True)
    Path(doc.file_path).unlink(missing_ok=True)
    slides.clear_cache()
    return Response(status_code=204)


@router.get("/{document_id}/slides", response_model=SlidesOut)
def list_slides(document_id: int, db: Session = Depends(get_db),
                user: User | None = Depends(require_user)) -> SlidesOut:
    """Tiêu đề và ghi chú giảng viên của từng slide (lấy từ chunk chứa slide đó)."""
    doc = get_visible(db, user, document_id)
    n = slides.slide_count(doc.id)
    chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == doc.id, Chunk.is_active)
                             .order_by(Chunk.slide_no)))
    infos = []
    for no in range(1, n + 1):
        c = next((c for c in chunks if c.slide_no is not None and c.slide_no <= no <= (c.slide_end or c.slide_no)),
                 None)
        size = slides.png_size(doc.id, no) or (None, None)
        infos.append(SlideInfo(slide_no=no, title=c.title if c else None, notes=c.notes if c else None,
                               width=size[0], height=size[1]))
    return SlidesOut(document_id=doc.id, num_slides=n, slides=infos)


@router.get("/{document_id}/slides/{slide_no}/image")
def get_slide_image(
    document_id: int,
    slide_no: int,
    highlight: str | None = Query(None, max_length=2000, description="Đoạn văn cần tô vàng trên slide"),
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
) -> Response:
    doc = get_visible(db, user, document_id)
    if not 1 <= slide_no <= max(slides.slide_count(doc.id), 1):
        raise HTTPException(404, "Không có slide này")
    data = slides.slide_image(doc, slide_no, highlight)
    if data is None:
        raise HTTPException(404, "Chưa có ảnh cho slide này")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{document_id}/questions/generate", response_model=DocumentOut)
def generate_more(
    document_id: int, body: GenerateMoreIn, background: BackgroundTasks, db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
) -> DocumentOut:
    doc = get_editable(db, user, document_id)
    _check_busy(db, user)
    if not unrestricted(user) and body.n is not None and body.n > MAX_GENERATE_STUDENT:
        raise HTTPException(400, f"Mỗi lần sinh thêm tối đa {MAX_GENERATE_STUDENT} câu")
    if doc.status != "ready":
        raise HTTPException(409, "Tài liệu đang xử lý, thử lại sau")
    doc.status = "generating"
    db.commit()
    background.add_task(run_generate_more, doc.id, body.slide_from, body.slide_to, body.n)
    return _to_out(db, doc, user)
