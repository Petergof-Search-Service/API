from typing import LiteralString

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.dependencies import validate_user
from app.db.models import (
    User,
    Chat,
    create_users_activity,
    MessageRole,
    save_message,
    UserHistory,
)
from app.db.schemas import AnswerResponse, RagQuestion, HistoryResponse, HistoryMessage
from app.db.session import get_db
from rag.get_indexes import get_indexes, get_indexes_names2ids
from rag.main import get_answer

router = APIRouter(dependencies=[Depends(validate_user)])

tasks: dict[str, bool | tuple[str, LiteralString] | str] = {}


async def update_users_activity(
    user: User = Depends(validate_user), db: AsyncSession = Depends(get_db)
) -> None:
    await create_users_activity(db, user)


@router.post("/answer", status_code=200, response_model=AnswerResponse)
async def get_answer_from_rag(
    question_schema: RagQuestion,
    _: None = Depends(update_users_activity),
    user: User = Depends(validate_user),
    db: AsyncSession = Depends(get_db),
) -> AnswerResponse:
    indexes = await get_indexes(to_sort=True)
    if question_schema.index not in indexes:
        raise HTTPException(status_code=404, detail="Index not found")

    chat = await db.get(Chat, question_schema.chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await db.execute(
        select(User).options(joinedload(User.settings)).where(User.id == user.id)
    )
    user_with_settings = result.scalar_one()
    settings = user_with_settings.settings

    indexesname2ids = await get_indexes_names2ids()

    history_result = await db.execute(
        select(UserHistory)
        .where(
            UserHistory.user_id == user.id,
            UserHistory.chat_id == question_schema.chat_id,
        )
        .order_by(UserHistory.created_at)
    )
    dialog_history = [
        {"role": row.role, "content": row.content}
        for row in history_result.scalars().all()
    ]

    if chat.title == "Новый чат":
        chat.title = question_schema.question[:500]
        await db.flush()

    await save_message(
        db,
        user,
        MessageRole.user,
        question_schema.question,
        chat_id=question_schema.chat_id,
    )

    answer, context = await get_answer(
        vector_store_id=indexesname2ids[question_schema.index],
        question=question_schema.question,
        temp=settings.temperature,
        prompt=settings.prompt,
        dialog_history=dialog_history,
    )

    await save_message(
        db,
        user,
        MessageRole.assistant,
        answer,
        chat_id=question_schema.chat_id,
        context=context,
    )

    await db.commit()
    return AnswerResponse(answer=answer, context=context)


@router.get("/history", status_code=200, response_model=HistoryResponse)
async def get_history(
    chat_id: int,
    user: User = Depends(validate_user),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    chat = await db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await db.execute(
        select(UserHistory)
        .where(UserHistory.user_id == user.id, UserHistory.chat_id == chat_id)
        .order_by(UserHistory.created_at)
    )
    messages = result.scalars().all()
    return HistoryResponse(
        messages=[HistoryMessage.model_validate(m) for m in messages]
    )
