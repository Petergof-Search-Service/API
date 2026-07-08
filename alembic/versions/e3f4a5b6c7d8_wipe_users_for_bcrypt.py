"""wipe_users_for_bcrypt

Смена схемы хеширования паролей SHA-256 → bcrypt (API-01) необратима для
существующих строк: их пароли в открытом виде неизвестны, а старый SHA-256-хеш
против bcrypt.checkpw не проходит. Ленивую миграцию решили не делать (MVP,
единственный пользователь), поэтому просто вычищаем все учётки — после апгрейда
аккаунт(ы) создаются заново и сразу получают bcrypt-хеш.

TRUNCATE ... CASCADE удаляет users и ВСЁ, что на них ссылается (users_setting,
chats, users_history, users_activity, files, членства user_organization).
Организации и индексы — org-level, на users не ссылаются, поэтому остаются.
RESTART IDENTITY сбрасывает счётчики id для чистого старта.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-08 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Одноразовый сброс учёток под переход на bcrypt (API-01).
    op.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE")


def downgrade() -> None:
    # Данные удалены безвозвратно — откат невозможен.
    pass
