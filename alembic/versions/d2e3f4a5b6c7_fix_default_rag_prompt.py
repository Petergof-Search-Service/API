"""fix_default_rag_prompt

Переводит существующие строки ``users_setting`` со старого дефолтного промпта
(который содержал «Игнорируйте контекст, если считаете его нерелевантным» и
опечатку «информация.. Ответь на вопрос: ») на новый строгий grounded-промпт
(``DEFAULT_RAG_PROMPT``).

Дефолт колонки задаётся на уровне ORM (``default=DEFAULT_RAG_PROMPT``) и влияет
только на НОВЫЕ строки — уже существующие пользователи остались бы на старом,
провоцирующем галлюцинации промпте без этой миграции данных.

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-07-08 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import bindparam
from sqlalchemy.sql import text

from app.core.prompts import DEFAULT_RAG_PROMPT

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Точная старая дефолтная строка колонки prompt (до этой правки).
OLD_DEFAULT_PROMPT = (
    "Вы ассистируете научного руководителя музейного комплекса Петергоф. "
    "Ниже вам дан контекст, откуда брать информацию. Разрешено брать сразу "
    "несколько текстов. Отвечайте на вопросы, которые он задает. Игнорируйте "
    "контекст, если считаете его нерелевантным. Вместе с ответом также напишите "
    "название файла и страницу, откуда была взята информация.. Ответь на вопрос: "
)


def upgrade() -> None:
    # Мигрируем только тех, кто остался на старом дефолте, не трогая
    # пользователей, которые уже поменяли промпт под себя.
    stmt = text(
        "UPDATE users_setting SET prompt = :new_prompt WHERE prompt = :old_prompt"
    ).bindparams(
        bindparam("new_prompt", value=DEFAULT_RAG_PROMPT),
        bindparam("old_prompt", value=OLD_DEFAULT_PROMPT),
    )
    op.execute(stmt)


def downgrade() -> None:
    stmt = text(
        "UPDATE users_setting SET prompt = :old_prompt WHERE prompt = :new_prompt"
    ).bindparams(
        bindparam("new_prompt", value=DEFAULT_RAG_PROMPT),
        bindparam("old_prompt", value=OLD_DEFAULT_PROMPT),
    )
    op.execute(stmt)
