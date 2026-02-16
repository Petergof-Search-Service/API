from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.security import oauth2_scheme
from app.db.models.user import get_user, User
from app.db.session import get_db


async def validate_user(token: Annotated[str, Depends(oauth2_scheme)],
                        db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        if email is None or token_type != "access":
            raise credentials_exception

        user = await get_user(db, email)
        if not user:
            raise credentials_exception

        return user[0]

    except InvalidTokenError:
        raise credentials_exception


def validate_admin_user(user: User = Depends(validate_user)):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
