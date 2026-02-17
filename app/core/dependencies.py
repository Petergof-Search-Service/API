from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.security import oauth2_scheme
from app.db.models.user import User, get_user
from app.db.session import get_db


async def validate_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate JWT token and return user.

    Args:
        token: JWT access token from Authorization header
        db: Database session

    Returns:
        User: Authenticated user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])

        email = payload.get("sub")
        if not isinstance(email, str) or not email:
            raise credentials_exception

        token_type = payload.get("type")
        if token_type != "access":
            raise credentials_exception

        user = await get_user(db, email)
        if user is None:
            raise credentials_exception

        return user

    except InvalidTokenError:
        raise credentials_exception


async def validate_admin_user(user: Annotated[User, Depends(validate_user)]) -> User:
    """Validate that user is admin.

    Args:
        user: Authenticated user

    Returns:
        User: Admin user

    Raises:
        HTTPException: If user is not admin
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return user
