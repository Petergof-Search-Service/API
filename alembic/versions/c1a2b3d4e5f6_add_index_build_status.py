"""add_index_build_status

Даёт таблице `indexes` durable-состояние сборки, чтобы:
- строка создавалась сразу (status=building, vector_store_id может быть NULL на старте),
- фоновый поллер продвигал статус (building → ready/failed) без busy-wait,
- редеплой не терял «строящиеся» индексы (состояние живёт в БД).

Существующие строки создавались только после успешной сборки → бэкфилл в 'ready'.

Revision ID: c1a2b3d4e5f6
Revises: b3e7f1a2c4d9
Create Date: 2026-07-07 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "b3e7f1a2c4d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Все ранее созданные индексы по определению готовы (строка писалась только
    # после busy-poll до completed) → server_default='ready' бэкфиллит их.
    op.add_column(
        "indexes",
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
    )
    op.add_column(
        "indexes",
        sa.Column("file_counts", sa.JSON(), nullable=True),
    )
    op.add_column(
        "indexes",
        sa.Column("error_message", sa.String(), nullable=True),
    )
    op.add_column(
        "indexes",
        sa.Column("source_file_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "indexes",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # На раннем этапе создания строка существует раньше, чем получен id стора.
    op.alter_column("indexes", "vector_store_id", nullable=True)


def downgrade() -> None:
    # После этой фичи упавшие сборки могут иметь vector_store_id IS NULL
    # (create не завершился) — их надо убрать до восстановления NOT NULL.
    op.execute("DELETE FROM indexes WHERE vector_store_id IS NULL")
    op.alter_column("indexes", "vector_store_id", nullable=False)
    op.drop_column("indexes", "updated_at")
    op.drop_column("indexes", "source_file_ids")
    op.drop_column("indexes", "error_message")
    op.drop_column("indexes", "file_counts")
    op.drop_column("indexes", "status")
