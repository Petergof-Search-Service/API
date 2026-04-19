from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import validate_user
from app.db.models import User, Chat, create_chat
from app.db.schemas import ChatResponse, ChatListResponse
from app.db.session import get_db

router = APIRouter(dependencies=[Depends(validate_user)])


@router.post("/chats", status_code=201, response_model=ChatResponse)
async def create_new_chat(
    user: User = Depends(validate_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    chat = await create_chat(db, user)
    await db.commit()
    return ChatResponse.model_validate(chat)


@router.get("/chats", status_code=200, response_model=ChatListResponse)
async def list_chats(
    user: User = Depends(validate_user),
    db: AsyncSession = Depends(get_db),
) -> ChatListResponse:
    result = await db.execute(
        select(Chat).where(Chat.user_id == user.id).order_by(Chat.created_at.desc())
    )
    chats = result.scalars().all()
    return ChatListResponse(chats=[ChatResponse.model_validate(c) for c in chats])


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: int,
    user: User = Depends(validate_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    chat = await db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    await db.delete(chat)
    await db.commit()
