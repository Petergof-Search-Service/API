import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import OrgMembership, require_org_admin, require_org_member
from app.core.s3 import PRESIGNED_EXPIRES_IN, generate_upload_presigned_url
from app.core.ws import manager
from app.db.models.file import File
from app.db.models.org_index import OrgIndex
from app.db.schemas import (
    FilesResponse,
    IndexRecord,
    IndexesResponse,
    IndexRequest,
    RagFileRecord,
    StatusResponse,
    UploadLinkRequest,
    UploadLinkResponse,
)
from app.db.session import get_db, AsyncSessionLocal

from rag.get_files import get_files_names2ids
from rag.create_index import create_index as create_index_from_rag

router = APIRouter()

index_task = False


async def _save_index_to_db(
    org_id: int, name: str, vector_store_id: str
) -> IndexRecord:
    async with AsyncSessionLocal() as db:
        index = OrgIndex(org_id=org_id, name=name, vector_store_id=vector_store_id)
        db.add(index)
        await db.commit()
        await db.refresh(index)
        return IndexRecord.model_validate(index)


async def _get_chunks_names_for_ids(file_ids: list[int], org_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(File).where(File.id.in_(file_ids), File.org_id == org_id)
        )
        files = result.scalars().all()
        return [f"{Path(f.system_key).stem}.chunks.jsonl" for f in files]


@router.get("/indexes", status_code=200, response_model=IndexesResponse)
async def get_indexes(
    membership: Annotated[OrgMembership, Depends(require_org_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexesResponse:
    result = await db.execute(
        select(OrgIndex)
        .where(OrgIndex.org_id == membership.org_id)
        .order_by(OrgIndex.name)
    )
    indexes = result.scalars().all()
    return IndexesResponse(indexes=[IndexRecord.model_validate(i) for i in indexes])


@router.post("/indexes", status_code=200)
async def create_index(
    index_request: IndexRequest,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
) -> int:
    global index_task

    if index_task:
        raise HTTPException(status_code=409, detail="Index still running")

    index_task = True
    org_id = membership.org_id
    user_id = membership.user.id

    async def background_task() -> None:
        global index_task
        try:
            await manager.send(
                user_id,
                {
                    "type": "index_status",
                    "status": "running",
                    "name": index_request.name,
                },
            )

            chunks_names = await _get_chunks_names_for_ids(
                index_request.file_ids, org_id
            )
            filenames2ids = await get_files_names2ids()
            yandex_file_ids = [
                filenames2ids[name] for name in chunks_names if name in filenames2ids
            ]
            if not yandex_file_ids:
                raise ValueError("None of the selected files are indexed in Yandex")

            result = await create_index_from_rag(index_request.name, yandex_file_ids)
            saved = await _save_index_to_db(
                org_id, result["name"], result["vector_store_id"]
            )

            await manager.send(
                user_id,
                {
                    "type": "index_status",
                    "status": "done",
                    "index": {
                        "id": saved.id,
                        "name": saved.name,
                        "created_at": saved.created_at.isoformat(),
                    },
                },
            )
        except Exception as e:
            print(e)
            await manager.send(
                user_id,
                {
                    "type": "index_status",
                    "status": "error",
                    "error": str(e),
                },
            )
        finally:
            index_task = False

    asyncio.create_task(background_task())

    return 200


@router.get("/rag-files", status_code=200, response_model=FilesResponse)
async def get_rag_files(
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FilesResponse:
    result = await db.execute(
        select(File)
        .where(File.org_id == membership.org_id, File.status == "indexed")
        .order_by(File.original_filename)
    )
    files = result.scalars().all()
    return FilesResponse(
        files=[RagFileRecord(id=f.id, name=f.original_filename) for f in files]
    )


@router.get(
    "/indexes/status",
    status_code=200,
    dependencies=[Depends(require_org_admin)],
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
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadLinkResponse:
    try:
        upload_url, s3_key = generate_upload_presigned_url(body.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    s3_url = f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET_NAME}/{s3_key}"
    file = File(
        user_id=membership.user.id,
        org_id=membership.org_id,
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
