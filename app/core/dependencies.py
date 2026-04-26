from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.security import oauth2_scheme
from app.db.models.organization import UserOrganization
from app.db.models.user import User, get_user
from app.db.session import get_db


@dataclass
class OrgMembership:
    user: User
    org_id: int
    role: str

    @property
    def is_admin_or_owner(self) -> bool:
        return self.role in ("admin", "owner")

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


async def validate_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )

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
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    return user


async def require_org_member(
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_organization_id: Annotated[int | None, Header()] = None,
) -> OrgMembership:
    if x_organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Organization-ID header is required",
        )

    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.org_id == x_organization_id,
        )
    )
    uo = result.scalar_one_or_none()
    if uo is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    return OrgMembership(user=user, org_id=x_organization_id, role=uo.role)


async def require_org_admin(
    membership: Annotated[OrgMembership, Depends(require_org_member)],
) -> OrgMembership:
    if not membership.is_admin_or_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner role required",
        )
    return membership


async def require_org_owner(
    membership: Annotated[OrgMembership, Depends(require_org_member)],
) -> OrgMembership:
    if not membership.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )
    return membership
