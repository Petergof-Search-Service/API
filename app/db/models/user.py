from sqlalchemy import Column, Integer, String, DateTime, select, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.db.models.user_settings import UserSetting
from app.db.schemas import UserCreate
from app.core import get_hash


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String)
    hashed_password = Column(String)
    is_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    settings = relationship("UserSetting", uselist=False, back_populates="user", cascade="all, delete-orphan")


    def __repr__(self):
        return f"<User(email={self.email}, hashed_password={self.hashed_password})>"


async def create_user(db: AsyncSession, user_db: UserCreate):
    db_item = User(
        email=user_db.email,
        hashed_password=get_hash(user_db.password),
        settings=UserSetting()
    )
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


async def get_user(db: AsyncSession, user_email: str):
    query = select(User).where(User.email == user_email)
    result = await db.execute(query)
    return result.first()
