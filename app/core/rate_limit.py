"""Синглтон rate-лимитера (slowapi) и key-функции для него.

Вынесено в отдельный модуль (не в `main.py`), чтобы эндпоинты импортировали
`limiter` без циклической зависимости `main ↔ endpoints`.

Хранилище счётчиков — in-memory на процесс. Развёртывание идёт на 1 uvicorn-воркере
(см. корневой `CLAUDE.md`), поэтому этого достаточно; при `--workers>1` или
горизонтальном масштабировании потребуется общий стор (Redis).
"""

import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core import settings

# Ключ по умолчанию — IP клиента. Auth-эндпоинты лимитируются по IP,
# `/answer` — по идентичности (см. user_or_ip_key ниже).
limiter = Limiter(key_func=get_remote_address)


def user_or_ip_key(request: Request) -> str:
    """Ключ лимита по идентичности пользователя, с фолбэком на IP.

    key-функция slowapi получает только `request`, поэтому идентичность берём
    из JWT в заголовке `Authorization: Bearer`, а не из `Depends(validate_user)`.
    Токен декодируется тем же секретом/алгоритмом, что и в `dependencies.validate_user`.
    Любая ошибка декодирования или отсутствие `sub` → фолбэк на лимит по IP.
    """
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            sub = payload.get("sub")
            if isinstance(sub, str) and sub:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass

    # str(...): get_remote_address без stubs slowapi виден mypy как Any (warn_return_any).
    return str(get_remote_address(request))
