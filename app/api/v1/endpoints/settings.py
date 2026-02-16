from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.dependencies import validate_user
from app.db.models import User
from app.db.models import apply_update_settings
from app.db.session import get_db
from app.db.schemas import SettingModel

router = APIRouter(dependencies=[Depends(validate_user)])


@router.post("/settings", status_code=200, response_model=SettingModel)
async def update_settings(new_settings: SettingModel, user: User = Depends(validate_user),
                          db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(joinedload(User.settings)).where(User.id == user.id)
    )
    user_with_settings = result.scalar_one()
    user_settings = user_with_settings.settings

    return await apply_update_settings(new_settings, user_settings, db)


@router.get("/settings", status_code=200, response_model=SettingModel)
async def get_settings(user: User = Depends(validate_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(joinedload(User.settings)).where(User.id == user.id)
    )
    user_with_settings = result.scalar_one()
    return user_with_settings.settings
