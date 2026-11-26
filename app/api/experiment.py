"""Thử nghiệm với sinh viên (Mốc 3, G4/G5): tiến trình 3 bước, tạo đề luyện tập, ghi phản hồi."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.quizzes import _load_quiz
from app.auth.deps import effective_user_id, require_user
from app.db import get_db
from app.experiment import load_config, progress
from app.generation.quiz_sampler import EmptyBankError, create_quiz
from app.models import Attempt, Feedback, Quiz, User
from app.schemas import QuizOut, Scope

router = APIRouter(tags=["experiment"])
OptUser = User | None

FEEDBACK_KINDS = {"diag_item": (0, 2), "diag_overall": (1, 5), "explain_overall": (1, 5),
                  "practice_useful": (1, 5), "comment": (None, None)}


class ExperimentState(BaseModel):
    active: bool                     # có thử nghiệm đang mở không
    member: bool = False             # mã này có trong danh sách không
    name: str | None = None
    step: str | None = None          # "1" | "2" | "3" | "done"
    quiz1_id: int | None = None
    quiz2_id: int | None = None
    practice_n: int | None = None
    attempt1_id: int | None = None
    practice_quiz_id: int | None = None
    attempt2_id: int | None = None
    feedback_kinds: dict[str, list[str]] = {}   # attempt_id → các loại khảo sát chung đã trả lời (để không hỏi lại)


class PracticeIn(BaseModel):
    user_id: int | None = None      # bỏ qua khi đã đăng nhập (lấy từ phiên)


class FeedbackIn(BaseModel):
    user_id: int | None = None      # bỏ qua khi đã đăng nhập (lấy từ phiên)
    attempt_id: int
    question_id: int | None = None
    kind: str
    value: int | None = None
    comment: str | None = Field(default=None, max_length=2000)


def _user(db: Session, user_id: int | None) -> User:
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(404, "Không tìm thấy người học")
    return user


@router.get("/experiment/state", response_model=ExperimentState)
def state(user_id: int | None = None, db: Session = Depends(get_db),
          me: OptUser = Depends(require_user)) -> ExperimentState:
    user_id = effective_user_id(me, user_id)
    if user_id is None:
        raise HTTPException(422, "Thiếu user_id")
    cfg = load_config()
    if not cfg:
        return ExperimentState(active=False)
    user = _user(db, user_id)
    p = progress(db, cfg, user)
    base = {"active": True, "name": cfg.get("name"), "quiz1_id": cfg["quiz1_id"], "quiz2_id": cfg["quiz2_id"],
            "practice_n": cfg.get("practice_n", 10)}
    if p is None:
        return ExperimentState(**base, member=False)
    done: dict[str, list] = {}
    for att, kind in db.execute(select(Feedback.attempt_id, Feedback.kind).where(
            Feedback.user_id == user.id, Feedback.question_id.is_(None))):
        done.setdefault(str(att), []).append(kind)
    return ExperimentState(**base, member=True, step=p.step, attempt1_id=p.attempt1_id,
                           practice_quiz_id=p.practice_quiz_id, attempt2_id=p.attempt2_id, feedback_kinds=done)


@router.post("/experiment/practice", response_model=QuizOut)
def practice(body: PracticeIn, db: Session = Depends(get_db), me: OptUser = Depends(require_user)) -> QuizOut:
    """Đề luyện tập của bước 2. Đã tạo mà chưa nộp thì trả lại đề đó (tải lại trang không sinh đề mới)."""
    cfg = load_config()
    if not cfg:
        raise HTTPException(404, "Chưa mở thử nghiệm")
    user = _user(db, effective_user_id(me, body.user_id))
    p = progress(db, cfg, user)
    if p is None:
        raise HTTPException(403, "Mã này không có trong danh sách thử nghiệm")
    if p.step != "2":
        raise HTTPException(409, "Chưa tới bước luyện tập" if p.step == "1" else "Đã luyện tập xong")
    if p.practice_quiz_id:
        return _load_quiz(db, db.get(Quiz, p.practice_quiz_id))
    mode = "weakness" if p.group == "A" else "normal"
    try:
        res = create_quiz(db, Scope(**cfg["scope"]), int(cfg.get("practice_n", 10)), None, None, mode, user.id)
    except EmptyBankError as exc:
        raise HTTPException(409, str(exc)) from exc
    # Đánh dấu là đề luyện tập của thử nghiệm: chỉ đề có dấu này mới tính là đã qua bước 2 (đề tự tạo thì không)
    res.quiz.scope = {**(res.quiz.scope or {}), "experiment": cfg.get("name"), "practice": True}
    db.commit()
    # Không lộ nhóm: bỏ thông báo "chưa đủ dữ liệu điểm yếu" (nếu có) khỏi giao diện; vẫn lưu mode trong DB
    return _load_quiz(db, res.quiz, None)


@router.post("/feedback", status_code=204)
def feedback(body: FeedbackIn, db: Session = Depends(get_db), me: OptUser = Depends(require_user)) -> None:
    body.user_id = effective_user_id(me, body.user_id)
    if body.user_id is None:
        raise HTTPException(422, "Thiếu user_id")
    if body.kind not in FEEDBACK_KINDS:
        raise HTTPException(400, f"kind phải là một trong {sorted(FEEDBACK_KINDS)}")
    lo, hi = FEEDBACK_KINDS[body.kind]
    if lo is not None and (body.value is None or not lo <= body.value <= hi):
        raise HTTPException(400, f"value của {body.kind} phải trong [{lo}, {hi}]")
    att = db.get(Attempt, body.attempt_id)
    if att is None or att.user_id != body.user_id:
        raise HTTPException(404, "Không tìm thấy bài làm của người học này")
    old = db.scalar(select(Feedback).where(
        Feedback.user_id == body.user_id, Feedback.attempt_id == body.attempt_id, Feedback.kind == body.kind,
        Feedback.question_id.is_(None) if body.question_id is None else Feedback.question_id == body.question_id))
    if old:
        old.value, old.comment = body.value, body.comment
    else:
        db.add(Feedback(**body.model_dump()))
    db.commit()
