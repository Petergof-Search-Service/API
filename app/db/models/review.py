from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.db.schemas import Review as ReviewCreate


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    question = Column(String)
    model_answer = Column(String)
    is_ok = Column(Boolean)
    corrected_answer = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Review(question={self.question}, model_answer={self.model_answer}, is_ok={self.is_ok}, corrected_answer={self.corrected_answer})>"


async def create_review(db: AsyncSession, review: ReviewCreate):
    db_item = Review(
        question=review.question,
        model_answer=review.model_answer,
        is_ok=review.is_ok,
        corrected_answer=review.correct_answer
    )
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item
