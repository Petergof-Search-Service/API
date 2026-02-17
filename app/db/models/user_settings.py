from sqlalchemy import Integer, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.db.schemas import SettingModel

from datetime import datetime


class UserSetting(Base):
    __tablename__ = "users_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    prompt: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="Вы ассистируете научного руководителя музейного комплекса Петергоф. Ниже вам дан контекст, откуда брать информацию. Разрешено брать сразу несколько текстов. Отвечайте на вопросы, которые он задает. Игнорируйте контекст, если считаете его нерелевантным. Вместе с ответом также напишите название файла и страницу, откуда была взята информация.. Ответь на вопрос: ",
    )
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    count_vector: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    count_fulltext: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSetting(prompt={self.prompt}, temperature={self.temperature}, count_vector={self.count_vector}, count_fulltext={self.count_fulltext})>"


async def apply_update_settings(
    new_settings: SettingModel, settings: UserSetting, session: AsyncSession
) -> UserSetting:
    for field, value in new_settings.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)

    await session.commit()
    await session.refresh(settings)
    return settings
