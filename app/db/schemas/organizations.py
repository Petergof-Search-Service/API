from pydantic import BaseModel, field_validator

from app.db.schemas.user import normalize_email


class OrgInfo(BaseModel):
    id: int
    name: str
    role: str  # 'user', 'admin', 'owner'


class OrganizationsResponse(BaseModel):
    organizations: list[OrgInfo]


class MemberInfo(BaseModel):
    user_id: int
    email: str
    role: str


class MembersResponse(BaseModel):
    members: list[MemberInfo]


class AddMemberRequest(BaseModel):
    email: str
    role: str  # 'user' or 'admin'

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class UpdateRoleRequest(BaseModel):
    role: str  # 'user' or 'admin'
