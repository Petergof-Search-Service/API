import asyncio
import threading
import time

from fastapi import APIRouter, Depends, UploadFile, HTTPException

from app.core.dependencies import validate_user, validate_admin_user
from rag import get_files as get_files_from_rag
from rag import get_indexes as get_indexes_from_rag
from rag import create_index as create_index_from_rag
from ocr import ApiOCR
from app.db.schemas import FilesResponse, IndexesResponse, OcrStatusResponse, IndexRequest, \
    StatusResponse

router = APIRouter(dependencies=[Depends(validate_user)])
ocr = ApiOCR()

index_task = False


@router.get("/indexes", status_code=200, response_model=IndexesResponse)
async def get_indexes():
    return IndexesResponse(indexes=get_indexes_from_rag())


@router.post("/indexes", status_code=200, dependencies=[Depends(validate_admin_user)])
async def create_index(index_request: IndexRequest):
    global index_task

    if index_task:
        raise HTTPException(status_code=409, detail="Index still running")

    index_task = True

    def background_task():
        global index_task
        try:
            create_index_from_rag(index_request.name, index_request.file_names)
            index_task = False
        except Exception as e:
            print(e)
            index_task = False

    thread = threading.Thread(target=background_task)
    thread.start()

    return 200


@router.get("/indexes/status", status_code=200, dependencies=[Depends(validate_admin_user)])
async def get_index_status():
    if index_task:
        return StatusResponse(status="still running")
    else:
        return StatusResponse(status="not running")


@router.get("/files", status_code=200, response_model=FilesResponse,
            dependencies=[Depends(validate_admin_user)])
async def get_files():
    return FilesResponse(files=get_files_from_rag())


@router.post("/files", dependencies=[Depends(validate_admin_user)])
async def push_to_ocr(file: UploadFile):
    if file.filename in get_files_from_rag():
        raise HTTPException(status_code=409, detail="File already uploaded")
    if await ocr.is_running():
        return HTTPException(status_code=409, detail="OCR already running")
    content = await file.read()
    asyncio.create_task(ocr.upload_pdf(content, file.filename[:-4]))
    return 200


@router.get("/files/status", dependencies=[Depends(validate_admin_user)],
            response_model=OcrStatusResponse)
async def get_ocr_status():
    return OcrStatusResponse(is_running=await ocr.is_running())
