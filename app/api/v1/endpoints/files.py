import asyncio
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.dependencies import OrgMembership, require_org_admin
from app.core.s3 import delete_s3_objects
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
from rag.delete_file import delete_rag_file

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/files", response_model=FileListResponse)
async def list_files(
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileListResponse:
    result = await db.execute(
        select(File)
        .where(File.org_id == membership.org_id)
        .order_by(File.created_at.desc())
    )
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
        stem = Path(body.system_key).stem
        result = await db.execute(
            select(File).where(File.system_key.like(f"%/{stem}.%"))
        )
        file = result.scalar_one_or_none()

    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    await _apply_status(file, body.status, body.error_message, db)
    return {"ok": True}


@router.patch("/files/{file_id}/status")
async def update_file_status(
    file_id: int,
    body: StatusUpdate,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    file = await _get_file_or_404(file_id, db)
    if file.org_id != membership.org_id:
        raise HTTPException(
            status_code=403, detail="File does not belong to this organization"
        )
    await _apply_status(file, body.status, body.error_message, db)
    return {"ok": True}


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    file = await _get_file_or_404(file_id, db)
    if file.org_id is not None and file.org_id != membership.org_id:
        raise HTTPException(
            status_code=403, detail="File does not belong to this organization"
        )
    stem = Path(file.system_key).stem

    s3_keys = [
        file.system_key,
        f"result/txt-files/{stem}.txt",
        f"result/json-files/{stem}.json",
        f"result/pdf-files/{stem}.pdf",
    ]
    await asyncio.to_thread(delete_s3_objects, s3_keys)

    try:
        await delete_rag_file(stem)
    except Exception:
        pass

    await db.delete(file)
    await db.commit()
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
        await websocket.accept()
        await websocket.close(code=4001)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
