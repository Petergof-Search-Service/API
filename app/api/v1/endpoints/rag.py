import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.dependencies import validate_user
from app.db.models import User, UserSetting
from app.db.session import get_db
from rag import get_answer, get_indexes
from app.db.schemas import TaskResponse, RagQuestion, StatusResponse

import time

router = APIRouter(dependencies=[Depends(validate_user)])

tasks = {}


@router.post("/answer", status_code=200, response_model=TaskResponse)
async def get_answer_from_rag(question_schema: RagQuestion, user: User = Depends(validate_user),
                              db: AsyncSession = Depends(get_db)):
    if question_schema.index not in get_indexes():
        raise HTTPException(status_code=404, detail="Index not found")

    result = await db.execute(
        select(User).options(joinedload(User.settings)).where(User.id == user.id)
    )
    user_with_settings = result.scalar_one()
    user_settings = user_with_settings.settings

    task_id = str(time.time())
    tasks[task_id] = False

    def background_task(settings: UserSetting):
        try:
            answer = asyncio.run(get_answer(index_name=question_schema.index,
                                            question=question_schema.question,
                                            temp=settings.temperature,
                                            faiss_search=settings.count_vector,
                                            bm_search=settings.count_fulltext,
                                            prompt=settings.prompt))
            tasks[task_id] = answer
        except Exception as e:
            tasks[task_id] = f"error: {str(e)}"

    thread = threading.Thread(target=background_task, args=(user_settings,))
    thread.start()

    return TaskResponse(task_id=task_id)


@router.get("/answer/status/{task_id}", response_model=StatusResponse)
async def check_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    if not tasks[task_id]:
        raise HTTPException(status_code=404, detail="Still running")
    response = tasks[task_id]
    tasks.pop(task_id)
    return StatusResponse(status=response[0] + '\n\n\n\n\n\n\n\n' + response[1])
