"""Tính lại mức độ khó ước lượng (easy/medium/hard) cho mọi câu accepted (kế hoạch v3, D4). Không gọi LLM.
  python -m app.maintenance.assign_difficulty
"""
from app.db import SessionLocal
from app.learner.difficulty import assign_levels

if __name__ == "__main__":
    with SessionLocal() as db:
        print("Số câu theo mức độ khó:", assign_levels(db))
