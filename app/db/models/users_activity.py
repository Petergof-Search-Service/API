from datetime import datetime

from app.db.models.user import User
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class UsersActivity(Base):
    __tablename__ = "users_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UsersActivity(user_id={self.user_id}, created_at={self.created_at})>"


async def create_users_activity(db: AsyncSession, user: User) -> UsersActivity:
    db_item = UsersActivity(user_id=user.id)
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item
