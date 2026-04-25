from typing import Annotated

import jwt
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.dependencies import validate_admin_user
from app.core.ws import manager
from app.db.models.file import File
from app.db.models.user import get_user
from app.db.schemas.files import (
    FileListResponse,
    FileRecord,
    ServiceStatusUpdate,
    StatusUpdate,
)
from app.db.session import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def require_service_key(
    x_service_key: Annotated[str | None, Header()] = None,
) -> None:
    if x_service_key != settings.CLOUD_FUNCTION_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service key"
        )


async def admin_or_service_key(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_service_key: Annotated[str | None, Header()] = None,
) -> None:
    """Accepts either x-service-key header (cloud functions) or admin JWT."""
    if x_service_key == settings.CLOUD_FUNCTION_API_KEY:
        return

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        email = payload.get("sub")
        if not isinstance(email, str) or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        user = await get_user(db, email)
        if user is None or not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
            )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_file_or_404(file_id: int, db: AsyncSession) -> File:
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return file


async def _apply_status(
    file: File, new_status: str, error_message: str | None, db: AsyncSession
) -> None:
    file.status = new_status
    file.error_message = error_message
    file.status_changed_at = func.now()
    await db.flush()
    await manager.send(
        file.user_id,
        {
            "type": "file_status",
            "file_id": file.id,
            "status": new_status,
            "error_message": error_message,
        },
    )


async def _ws_auth(token: str, db: AsyncSession) -> int:
    """Verify JWT for WS connection, return user_id."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        email = payload.get("sub")
        if not isinstance(email, str) or payload.get("type") != "access":
            raise ValueError
        user = await get_user(db, email)
        if user is None:
            raise ValueError
        return user.id
    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/files",
    response_model=FileListResponse,
    dependencies=[Depends(admin_or_service_key)],
)
async def list_files(db: Annotated[AsyncSession, Depends(get_db)]) -> FileListResponse:
    result = await db.execute(select(File).order_by(File.created_at.desc()))
    files = result.scalars().all()
    return FileListResponse(files=[FileRecord.model_validate(f) for f in files])


# Literal route must be registered before parameterized /files/{file_id}/status
@router.patch("/files/by-key/status", dependencies=[Depends(require_service_key)])
async def update_file_status_by_key(
    body: ServiceStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    result = await db.execute(select(File).where(File.system_key == body.system_key))
    file = result.scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    await _apply_status(file, body.status, body.error_message, db)
    return {"ok": True}


@router.patch("/files/{file_id}/status", dependencies=[Depends(validate_admin_user)])
async def update_file_status(
    file_id: int,
    body: StatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    file = await _get_file_or_404(file_id, db)
    await _apply_status(file, body.status, body.error_message, db)
    return {"ok": True}


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        user_id = await _ws_auth(token, db)
    except HTTPException:
        await websocket.close(code=4001)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
