from sqlalchemy import Integer, String, DateTime, select, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.models.user_settings import UserSetting
from app.db.schemas import UserCreate
from app.core import get_hash

from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String)
    hashed_password: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    settings: Mapped["UserSetting"] = relationship(
        "UserSetting", uselist=False, back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(email={self.email}, hashed_password={self.hashed_password})>"


async def create_user(db: AsyncSession, user_db: UserCreate) -> User:
    db_item = User(
        email=user_db.email, hashed_password=get_hash(user_db.password), settings=UserSetting()
    )
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


async def get_user(db: AsyncSession, user_email: str) -> User | None:
    query = select(User).where(User.email == user_email)
    result = await db.execute(query)
    return result.scalar_one_or_none()
