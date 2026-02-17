import hashlib
from datetime import datetime, timedelta, timezone
from typing import cast

import jwt
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/token")


def verify_refresh_token(refresh_token: str) -> dict:
    try:
        payload: dict = jwt.decode(
            refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )


def create_token(data: dict, expires_delta: timedelta = timedelta(minutes=15)) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.now(timezone.utc) + expires_delta})

    return cast(
        str,
        jwt.encode(
            to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        ),
    )


def get_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
