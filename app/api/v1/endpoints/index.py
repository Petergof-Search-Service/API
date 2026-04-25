import asyncio
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import validate_admin_user, validate_user
from app.core.s3 import PRESIGNED_EXPIRES_IN, generate_upload_presigned_url
from app.db.models.file import File
from app.db.models.user import User
from app.db.schemas import (
    IndexesResponse,
    IndexRequest,
    StatusResponse,
    UploadLinkRequest,
    UploadLinkResponse,
)
from app.db.session import get_db

from rag.create_index import create_index as create_index_from_rag
from rag.get_files import get_files_names2ids
from rag.get_indexes import get_indexes as get_indexes_from_rag

router = APIRouter(dependencies=[Depends(validate_user)])


index_task = False


@router.get("/indexes", status_code=200, response_model=IndexesResponse)
async def get_indexes() -> IndexesResponse:
    return IndexesResponse(indexes=await get_indexes_from_rag(to_sort=True))


# TODO: use grps here, not status
@router.post("/indexes", status_code=200, dependencies=[Depends(validate_admin_user)])
async def create_index(index_request: IndexRequest) -> int:
    global index_task

    if index_task:
        raise HTTPException(status_code=409, detail="Index still running")

    index_task = True

    def background_task() -> None:
        global index_task
        try:
            index_request_file_ids = []
            filenames2ids = asyncio.run(get_files_names2ids())
            for i in index_request.file_names:
                index_request_file_ids.append(filenames2ids[i])

            asyncio.run(
                create_index_from_rag(index_request.name, index_request_file_ids)
            )
            index_task = False
        except Exception as e:
            print(e)
            index_task = False

    thread = threading.Thread(target=background_task)
    thread.start()

    return 200


@router.get(
    "/indexes/status", status_code=200, dependencies=[Depends(validate_admin_user)]
)
async def get_index_status() -> StatusResponse:
    if index_task:
        return StatusResponse(status="still running")
    else:
        return StatusResponse(status="not running")


@router.post(
    "/files/upload-link",
    status_code=200,
    response_model=UploadLinkResponse,
)
async def get_upload_link(
    body: UploadLinkRequest,
    user: Annotated[User, Depends(validate_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadLinkResponse:
    """Возвращает presigned URL для загрузки файла в S3 (фронт загружает по этой ссылке PUT)."""
    try:
        upload_url, s3_key = generate_upload_presigned_url(body.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    s3_url = f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET_NAME}/{s3_key}"
    file = File(
        user_id=user.id,
        original_filename=body.filename.strip(),
        system_key=s3_key,
        s3_url=s3_url,
        status="pending_upload",
    )
    db.add(file)
    await db.flush()
    file_id = file.id

    return UploadLinkResponse(
        upload_url=upload_url,
        s3_key=s3_key,
        file_id=file_id,
        expires_in=PRESIGNED_EXPIRES_IN,
    )
