import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import validate_admin_user, validate_user
from app.core.s3 import PRESIGNED_EXPIRES_IN, generate_upload_presigned_url
from app.db.schemas import (
    FilesResponse,
    IndexesResponse,
    IndexRequest,
    OcrStatusResponse,
    StatusResponse,
    UploadLinkRequest,
    UploadLinkResponse,
)
from ocr import ApiOCR
from rag.create_index import create_index as create_index_from_rag
from rag.get_files import get_files as get_files_from_rag
from rag.get_files import get_files_names2ids
from rag.get_indexes import get_indexes as get_indexes_from_rag

router = APIRouter(dependencies=[Depends(validate_user)])
ocr = ApiOCR()

index_task = False


@router.get("/indexes", status_code=200, response_model=IndexesResponse)
async def get_indexes() -> IndexesResponse:
    return IndexesResponse(indexes=await get_indexes_from_rag(to_sort=True))


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


@router.get(
    "/files",
    status_code=200,
    response_model=FilesResponse,
    dependencies=[Depends(validate_admin_user)],
)
async def get_files() -> FilesResponse:
    return FilesResponse(files=await get_files_from_rag(to_sort=True))


@router.post(
    "/files/upload-link",
    status_code=200,
    response_model=UploadLinkResponse,
    dependencies=[Depends(validate_admin_user)],
)
async def get_upload_link(body: UploadLinkRequest) -> UploadLinkResponse:
    """Возвращает presigned URL для загрузки файла в S3 (фронт загружает по этой ссылке PUT)."""
    try:
        upload_url, s3_key = generate_upload_presigned_url(body.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UploadLinkResponse(
        upload_url=upload_url,
        s3_key=s3_key,
        expires_in=PRESIGNED_EXPIRES_IN,
    )


# TODO: remove all ocr in another repo
@router.get(
    "/files/status",
    dependencies=[Depends(validate_admin_user)],
    response_model=OcrStatusResponse,
)
async def get_ocr_status() -> OcrStatusResponse:
    return OcrStatusResponse(is_running=await ocr.is_running())
