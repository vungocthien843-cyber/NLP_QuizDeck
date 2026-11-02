"""Tạo đề từ ngân hàng câu hỏi và lấy đề để làm bài (mục 8)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.generation.quiz_sampler import EmptyBankError, create_quiz
from app.models import Question, Quiz, QuizQuestion
from app.schemas import QuizCreateIn, QuizOut, QuizQuestionOut

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


def _load_quiz(db: Session, quiz: Quiz) -> QuizOut:
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
        quiz_id=quiz.id, num_requested=quiz.num_questions, num_questions=len(questions), questions=questions
    )


@router.post("", response_model=QuizOut)
def post_quiz(body: QuizCreateIn, db: Session = Depends(get_db)) -> QuizOut:
    try:
        quiz = create_quiz(db, body.scope, body.n, body.bloom_mix)
    except EmptyBankError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _load_quiz(db, quiz)


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: int, db: Session = Depends(get_db)) -> QuizOut:
    quiz = db.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(404, "Không tìm thấy đề")
    return _load_quiz(db, quiz)
