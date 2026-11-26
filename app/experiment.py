"""Thử nghiệm với sinh viên (Mốc 3, G4/G5): cấu hình và tiến trình 3 bước của mỗi người.

Cấu hình do eval/student/chuan_bi.py ghi ra (mặc định eval/student/data/thu_nghiem.json, đổi bằng biến môi trường
EXPERIMENT_CONFIG):
  {"name", "scope": {...}, "quiz1_id", "quiz2_id", "practice_n", "members": {"<mã>": "A" | "B"}}
Nhóm A luyện bằng chế độ luyện điểm yếu, nhóm B luyện bằng đề thường cùng phạm vi, cùng số câu (đối chứng tích cực).
Người học KHÔNG được biết nhóm của mình: giao diện chỉ hiện "Luyện tập".

Bước của một người: 1 = làm Đề 1 → 2 = luyện tập → 3 = làm Đề 2 → done.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attempt, Quiz, User

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "eval" / "student" / "data" / "thu_nghiem.json"


def config_path() -> Path:
    return Path(os.environ.get("EXPERIMENT_CONFIG") or DEFAULT_PATH)


def load_config() -> dict | None:
    p = config_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass
class Progress:
    step: str                      # "1" | "2" | "3" | "done"
    group: str
    attempt1_id: int | None
    practice_quiz_id: int | None   # đề luyện tập đã tạo nhưng chưa nộp
    practice_attempt_id: int | None
    attempt2_id: int | None


def progress(db: Session, cfg: dict, user: User) -> Progress | None:
    # Danh sách thành viên có thể ghi bằng mã cũ, email @ictu.edu.vn, hoặc phần trước @ (mã sinh viên)
    members = {str(k).strip().lower(): v for k, v in (cfg.get("members") or {}).items()}
    email = (user.email or "").lower()
    keys = [(user.code or "").lower(), email, email.split("@")[0] if email else ""]
    group = next((members[k] for k in keys if k and k in members), None)
    if group is None:
        return None
    fixed = {cfg["quiz1_id"], cfg["quiz2_id"]}
    atts = list(db.scalars(select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.submitted_at)))
    a1 = next((a for a in atts if a.quiz_id == cfg["quiz1_id"]), None)
    a2 = next((a for a in atts if a.quiz_id == cfg["quiz2_id"]), None)
    practice_attempt = practice_quiz = None
    if a1:
        own = [q for q in db.scalars(select(Quiz).where(Quiz.user_id == user.id, Quiz.id.notin_(fixed),
                                                        Quiz.created_at >= a1.submitted_at).order_by(Quiz.created_at))
               if (q.scope or {}).get("practice")]          # chỉ đề do /experiment/practice tạo
        done = {a.quiz_id: a for a in atts}
        practice_attempt = next((done[q.id] for q in own if q.id in done), None)
        if practice_attempt is None and own:
            practice_quiz = own[-1].id
    step = "1" if not a1 else "2" if not practice_attempt else "3" if not a2 else "done"
    return Progress(step, group, a1 and a1.id, practice_quiz, practice_attempt and practice_attempt.id, a2 and a2.id)
