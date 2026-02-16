from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import validate_user
from app.db.models.review import create_review
from app.db.schemas import Review
from app.db.session import get_db

router = APIRouter(dependencies=[Depends(validate_user)])


@router.post("/review", status_code=200)
async def push_review(review: Review, db: AsyncSession = Depends(get_db)):
    await create_review(db, review)
    return 200
