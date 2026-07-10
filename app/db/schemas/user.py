from pydantic import BaseModel, field_validator


def normalize_email(value: str) -> str:
    """Приводим email к каноничному виду: без крайних пробелов, нижний регистр.

    Единая точка нормализации, чтобы `Foo@X.RU` и `foo@x.ru` считались одной учёткой
    и матчились с UNIQUE(users.email). Применяется на регистрации/приглашении и при
    логине (см. auth.py, organizations.py).
    """
    return value.strip().lower()


class UserCreate(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class UserGet(BaseModel):
    email: str
