from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Text, Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base
from app.db.models.user import User


class MessageRole(str, PyEnum):
    user = "user"
    assistant = "assistant"


class UserHistory(Base):
    __tablename__ = "users_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserHistory(user_id={self.user_id}, role={self.role}, created_at={self.created_at})>"


async def save_message(
    db: AsyncSession,
    user: User,
    role: MessageRole,
    content: str,
    context: str | None = None,
) -> UserHistory:
    db_item = UserHistory(user_id=user.id, role=role, content=content, context=context)
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item
