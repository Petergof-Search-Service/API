from pydantic import BaseModel

class UserCreate(BaseModel):
    email: str
    password: str

class UserGet(BaseModel):
    email: str
    is_admin: bool