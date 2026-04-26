from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import validate_user
from app.db.models.organization import Organization, UserOrganization
from app.db.models.user import User, get_user
from app.db.schemas.organizations import (
    AddMemberRequest,
    MemberInfo,
    MembersResponse,
    OrgInfo,
    OrganizationsResponse,
    UpdateRoleRequest,
)
from app.db.session import get_db

router = APIRouter(dependencies=[Depends(validate_user)])

_ASSIGNABLE_ROLES = {"user", "admin"}


async def _get_membership(
    user_id: int, org_id: int, db: AsyncSession
) -> UserOrganization | None:
    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def _require_owner(user: User, org_id: int, db: AsyncSession) -> None:
    uo = await _get_membership(user.id, org_id, db)
    if uo is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    if uo.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")


async def _require_admin_or_owner(user: User, org_id: int, db: AsyncSession) -> None:
    uo = await _get_membership(user.id, org_id, db)
    if uo is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    if uo.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin or owner role required")


@router.get("/organizations", response_model=OrganizationsResponse)
async def list_user_organizations(
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationsResponse:
    result = await db.execute(
        select(UserOrganization, Organization)
        .join(Organization, Organization.id == UserOrganization.org_id)
        .where(UserOrganization.user_id == user.id)
        .order_by(Organization.id)
    )
    orgs = [OrgInfo(id=org.id, name=org.name, role=uo.role) for uo, org in result.all()]
    return OrganizationsResponse(organizations=orgs)


@router.get("/organizations/{org_id}/members", response_model=MembersResponse)
async def list_members(
    org_id: int,
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MembersResponse:
    await _require_admin_or_owner(user, org_id, db)

    result = await db.execute(
        select(UserOrganization, User)
        .join(User, User.id == UserOrganization.user_id)
        .where(UserOrganization.org_id == org_id)
        .order_by(User.email)
    )
    members = [
        MemberInfo(user_id=u.id, email=u.email, role=uo.role) for uo, u in result.all()
    ]
    return MembersResponse(members=members)


@router.post("/organizations/{org_id}/members", status_code=201)
async def add_member(
    org_id: int,
    body: AddMemberRequest,
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    await _require_owner(user, org_id, db)

    if body.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")

    target = await get_user(db, body.email)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await _get_membership(target.id, org_id, db)
    if existing is not None:
        raise HTTPException(status_code=409, detail="User is already a member")

    db.add(UserOrganization(user_id=target.id, org_id=org_id, role=body.role))
    await db.commit()
    return {"ok": True}


@router.patch("/organizations/{org_id}/members/{user_id}")
async def update_member_role(
    org_id: int,
    user_id: int,
    body: UpdateRoleRequest,
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    await _require_owner(user, org_id, db)

    if body.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")

    uo = await _get_membership(user_id, org_id, db)
    if uo is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if uo.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot change owner's role")

    uo.role = body.role
    await db.commit()
    return {"ok": True}


@router.delete("/organizations/{org_id}/members/{user_id}")
async def remove_member(
    org_id: int,
    user_id: int,
    user: Annotated[User, Depends(validate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    await _require_owner(user, org_id, db)

    uo = await _get_membership(user_id, org_id, db)
    if uo is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if uo.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the owner")

    await db.delete(uo)
    await db.commit()
    return {"ok": True}
