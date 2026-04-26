from pydantic import BaseModel

from app.db.schemas.organizations import OrgInfo


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    organizations: list[OrgInfo] = []
