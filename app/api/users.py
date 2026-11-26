"""Người học (kế hoạch v3, C1 + D3): đăng nhập bằng mã tự nhập (không mật khẩu) và hồ sơ hiểu nhầm."""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_config
from app.auth.deps import can_view_user, require_login, require_user
from app.config import get_settings
from app.db import get_db
from app.learner.profile import top_weaknesses
from app.prompts import misconception_types
from app.models import Attempt, Document, Question, QuizQuestion, Response, User
from app.schemas import AttemptSummary, LoginIn, ProfileOut, UserOut, WeaknessOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> UserOut:
    """Mã đã có → trả người dùng đó (cập nhật tên nếu gửi tên mới); chưa có → tạo mới.
    Chỉ dùng cho giao diện cũ; khi bật AUTH_REQUIRED thì phải đăng nhập bằng Google."""
    if get_settings().auth_required:
        raise HTTPException(410, "Đăng nhập bằng mã đã ngừng, hãy đăng nhập bằng tài khoản Google của trường")
    code = body.code.strip().lower()
    if not code:
        raise HTTPException(400, "Mã người học không được rỗng")
    user = db.scalar(select(User).where(User.code == code))
    if user is None:
        user = User(code=code, display_name=(body.display_name or "").strip() or None)
        db.add(user)
    elif body.display_name and body.display_name.strip():
        user.display_name = body.display_name.strip()
    db.commit()
    return UserOut(user_id=user.id, code=user.code, display_name=user.display_name)


@router.get("/{user_id}/profile", response_model=ProfileOut)
def profile(user_id: int, db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> ProfileOut:
    if not can_view_user(user, user_id):
        raise HTTPException(403, "Không được xem hồ sơ của người khác")
    if db.get(User, user_id) is None:
        raise HTTPException(404, "Không tìm thấy người học")
    n_attempts = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)) or 0
    rows = db.execute(select(Response.is_correct, Response.error_type).where(Response.user_id == user_id)).all()
    by_type = Counter(e for ok, e in rows if not ok and e)
    weak = top_weaknesses(db, user_id, k=get_config().learner.weakness_top_k)
    return ProfileOut(
        user_id=user_id, n_attempts=n_attempts, n_answered=len(rows),
        accuracy=round(sum(ok for ok, _ in rows) / len(rows), 4) if rows else None,
        weaknesses=[WeaknessOut(**{k: w.get(k) for k in WeaknessOut.model_fields}) for w in weak],
        by_error_type=dict(by_type),
        error_type_names={k: v["ten"] for k, v in misconception_types().items()},
    )


@router.get("/me/attempts", response_model=list[AttemptSummary])
def my_attempts(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(require_login)) -> list[AttemptSummary]:
    """Lịch sử làm bài của người đang đăng nhập, mới nhất trước."""
    return attempt_summaries(db, user.id, limit)


def attempt_summaries(db: Session, user_id: int, limit: int = 100) -> list[AttemptSummary]:
    atts = db.scalars(select(Attempt).where(Attempt.user_id == user_id)
                      .order_by(Attempt.submitted_at.desc()).limit(min(limit, 500))).all()
    if not atts:
        return []
    quiz_ids = {a.quiz_id for a in atts}
    rows = db.execute(select(QuizQuestion.quiz_id, Question.id, Question.answer, Document.filename)
                      .join(Question, Question.id == QuizQuestion.question_id)
                      .join(Document, Document.id == Question.document_id)
                      .where(QuizQuestion.quiz_id.in_(quiz_ids))).all()
    names: dict[int, list[str]] = {}
    answers: dict[int, dict[int, str]] = {}
    for qz, qid, ans, fn in rows:
        n = (fn or "").rsplit(".", 1)[0].replace("_", " ")
        if n not in names.setdefault(qz, []):
            names[qz].append(n)
        answers.setdefault(qz, {})[qid] = ans
    out = []
    for a in atts:
        key = answers.get(a.quiz_id, {})
        correct = sum(1 for qid, ans in key.items() if (a.answers or {}).get(str(qid)) == ans)
        docs = names.get(a.quiz_id, [])
        label = " + ".join(docs) if len(docs) <= 2 else f"{len(docs)} bài"
        out.append(AttemptSummary(attempt_id=a.id, quiz_id=a.quiz_id, submitted_at=a.submitted_at.isoformat(),
                                  score_10=a.score or 0.0, num_questions=len(key), num_correct=correct,
                                  mode=a.mode or "normal", label=label or "Đề"))
    return out
