from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


# Статусы сборки индекса (durable, хранятся в колонке indexes.status).
#   building — vector store создаётся в AI Studio, поллер ждёт completed
#   ready    — индекс готов к использованию в чате
#   failed   — сборка упала (ошибка AI Studio / таймаут / ошибка создания)
INDEX_BUILDING = "building"
INDEX_READY = "ready"
INDEX_FAILED = "failed"


class OrgIndex(Base):
    __tablename__ = "indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # NULL на самом раннем этапе создания — до ответа vector_stores.create.
    vector_store_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=INDEX_BUILDING, server_default=INDEX_READY
    )
    # Прогресс сборки из AI Studio: {in_progress, completed, failed, cancelled, total}.
    file_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # Снапшот выбранных файлов (наши File.id) — для будущих retry/reindex.
    source_file_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def progress(self) -> dict | None:
        """Прогресс сборки для UI: {completed, total}. None, если счётчиков ещё нет."""
        if not self.file_counts:
            return None
        return {
            "completed": int(self.file_counts.get("completed", 0)),
            "total": int(self.file_counts.get("total", 0)),
        }
