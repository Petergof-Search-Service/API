from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status, Depends, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.dependencies import validate_user
from app.core.rate_limit import limiter
from app.core.security import create_token, verify_password, verify_refresh_token
from app.db.models.organization import Organization, UserOrganization
from app.db.schemas import Token, UserCreate, UserGet
from app.db.schemas.organizations import OrgInfo
from app.db.schemas.user import normalize_email
from app.db.session import get_db
from app.db.models.user import get_user, create_user, User

router = APIRouter()


async def _get_user_orgs(user: User, db: AsyncSession) -> list[OrgInfo]:
    result = await db.execute(
        select(UserOrganization, Organization)
        .join(Organization, Organization.id == UserOrganization.org_id)
        .where(UserOrganization.user_id == user.id)
        .order_by(Organization.id)
    )
    return [OrgInfo(id=org.id, name=org.name, role=uo.role) for uo, org in result.all()]


async def build_token_response(user: User, db: AsyncSession) -> Token:
    access_token_expires = timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    access_token = create_token(
        data={"sub": user.email, "type": "access"}, expires_delta=access_token_expires
    )
    refresh_token_expires = timedelta(days=int(settings.REFRESH_TOKEN_EXPIRE_DAYS))
    refresh_token = create_token(
        data={"sub": user.email, "type": "refresh"}, expires_delta=refresh_token_expires
    )
    orgs = await _get_user_orgs(user, db)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        organizations=orgs,
    )


@router.post("/refresh", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh_token(
    request: Request,
    refresh_token: str = Header(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    payload = verify_refresh_token(refresh_token)

    email = payload.get("sub")
    token_type = payload.get("type")
    if not email or token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user = await get_user(db, email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    return await build_token_response(user, db)


@router.post("/token", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
) -> Token:
    user: User | None = await get_user(db, normalize_email(form_data.username))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await build_token_response(user, db)


@router.post("/register", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def register_user(
    request: Request, user: UserCreate, db: AsyncSession = Depends(get_db)
) -> Token:
    # Атомарно: полагаемся на UNIQUE(users.email). Гонка двух регистраций одного email
    # — ровно одна пройдёт, вторая получит IntegrityError на commit → 409.
    try:
        new_user = await create_user(db, user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User already registered")

    return await build_token_response(new_user, db)


@router.get("/me", response_model=UserGet)
async def read_users_me(user: User = Depends(validate_user)) -> UserGet:
    return UserGet(email=user.email)
