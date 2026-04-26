from pydantic import BaseModel


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


class UpdateRoleRequest(BaseModel):
    role: str  # 'user' or 'admin'
