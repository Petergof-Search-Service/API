"""seed default organization «Петергоф»

Идемпотентно создаёт организацию по умолчанию, если её ещё нет. Нужна, потому что
организации нигде в коде не сидируются, а эндпоинта создания организации нет — без
этого сида на чистой БД (или после потери данных) система остаётся без единственной
рабочей организации, и «Петергоф» приходится вставлять руками.

Сид создаёт только саму организацию. Чтобы сделать зарегистрированного пользователя
её владельцем, добавьте членство отдельно (см. ALEMBIC_RECOVERY.md, раздел про
владельца) — здесь намеренно не заводим пользователя/пароль.

Revision ID: a7b3c9d1e2f4
Revises: b6bcf27f08c6
Create Date: 2026-07-11 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7b3c9d1e2f4"
down_revision: Union[str, None] = "b6bcf27f08c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_NAME = "Петергоф"


def upgrade() -> None:
    # Идемпотентно: ON CONFLICT по UNIQUE(name) — повторный накат ничего не делает,
    # а существующую организацию (в т.ч. созданную вручную) не трогает.
    op.get_bind().execute(
        sa.text(
            "INSERT INTO organizations (name) VALUES (:name) "
            "ON CONFLICT (name) DO NOTHING"
        ),
        {"name": DEFAULT_ORG_NAME},
    )


def downgrade() -> None:
    # Удаляем только саму организацию. Если на неё уже ссылаются files/indexes/
    # user_organizations (org_id) — FK не даст удалить, и это правильно.
    op.get_bind().execute(
        sa.text("DELETE FROM organizations WHERE name = :name"),
        {"name": DEFAULT_ORG_NAME},
    )
