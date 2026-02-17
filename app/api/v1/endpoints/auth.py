from datetime import timedelta
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.dependencies import validate_user
from app.core.security import create_token, get_hash, verify_refresh_token
from app.db.schemas import Token, UserCreate, UserGet
from app.db.session import get_db
from app.db.models.user import get_user, create_user, User

router = APIRouter()


def generate_tokens(user_email: str) -> Token:
    access_token_expires = timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    access_token = create_token(
        data={"sub": user_email, "type": "access"}, expires_delta=access_token_expires
    )
    refresh_token_expires = timedelta(days=int(settings.REFRESH_TOKEN_EXPIRE_DAYS))
    refresh_token = create_token(
        data={"sub": user_email, "type": "refresh"}, expires_delta=refresh_token_expires
    )
    return Token(
        access_token=access_token, refresh_token=refresh_token, token_type="bearer"
    )


# Feature: make refresh token unavailable after use
@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str = Header(), db: AsyncSession = Depends(get_db)
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

    return generate_tokens(email)


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await get_user(db, form_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = cast(User, user[0])
    if user.hashed_password != get_hash(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return generate_tokens(form_data.username)


@router.post("/register", response_model=Token)
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    existing_user = await get_user(db, user.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="User already registered")

    new_user = await create_user(db, user)
    return generate_tokens(new_user.email)


@router.get("/me", response_model=UserGet)
async def read_users_me(user: User = Depends(validate_user)) -> UserGet:
    return UserGet(
        email=user.email, is_admin=user.is_admin if user.is_admin is not None else False
    )
