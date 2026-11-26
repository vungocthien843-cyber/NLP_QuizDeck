"""Tạo đề từ ngân hàng câu hỏi và lấy đề để làm bài (mục 8)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.access import can_view_quiz, restrict_scope
from app.auth.deps import effective_user_id, require_user
from app.db import get_db
from app.generation.quiz_sampler import EmptyBankError, create_quiz
from app.models import Question, Quiz, QuizQuestion, User
from app.schemas import QuizCreateIn, QuizOut, QuizQuestionOut

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


def _load_quiz(db: Session, quiz: Quiz, notice: str | None = None) -> QuizOut:
    rows = db.execute(
        select(QuizQuestion.position, Question)
        .join(Question, Question.id == QuizQuestion.question_id)
        .where(QuizQuestion.quiz_id == quiz.id)
        .order_by(QuizQuestion.position)
    ).all()
    # Không trả answer / rationales / explanation để tránh lộ đáp án
    questions = [
        QuizQuestionOut(question_id=q.id, position=pos, stem=q.stem, options=q.options,
                        bloom_level=q.bloom_level) for pos, q in rows
    ]
    return QuizOut(
        quiz_id=quiz.id, num_requested=quiz.num_questions, num_questions=len(questions), questions=questions,
        mode=quiz.mode or "normal", difficulty=quiz.difficulty, notice=notice,
    )


@router.post("", response_model=QuizOut)
def post_quiz(body: QuizCreateIn, db: Session = Depends(get_db),
              user: User | None = Depends(require_user)) -> QuizOut:
    body.user_id = effective_user_id(user, body.user_id)
    if body.mode == "weakness" and body.user_id is None:
        raise HTTPException(400, "Chế độ luyện điểm yếu cần đăng nhập bằng mã người học")
    try:
        res = create_quiz(db, restrict_scope(db, user, body.scope), body.n, body.bloom_mix, body.difficulty, body.mode, body.user_id)
    except EmptyBankError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _load_quiz(db, res.quiz, res.notice)


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: int, db: Session = Depends(get_db), user: User | None = Depends(require_user)) -> QuizOut:
    quiz = db.get(Quiz, quiz_id)
    if not can_view_quiz(user, quiz):
        raise HTTPException(404, "Không tìm thấy đề")
    return _load_quiz(db, quiz)
