from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import OrgMembership, require_org_admin, require_org_member
from app.core.s3 import PRESIGNED_EXPIRES_IN, generate_upload_presigned_url
from app.db.models.file import File
from app.db.models.org_index import OrgIndex, INDEX_BUILDING, INDEX_FAILED
from app.db.schemas import (
    FilesResponse,
    IndexRecord,
    IndexesResponse,
    IndexRequest,
    RagFileRecord,
    UploadLinkRequest,
    UploadLinkResponse,
)
from app.db.session import get_db

from rag.get_files import get_files_names2ids
from rag.create_index import create_vector_store, delete_index

router = APIRouter()


async def _resolve_yandex_file_ids(
    db: AsyncSession, file_ids: list[int], org_id: int
) -> list[str]:
    """Наши File.id → id соответствующих chunks-файлов в AI Studio."""
    result = await db.execute(
        select(File).where(File.id.in_(file_ids), File.org_id == org_id)
    )
    files = result.scalars().all()
    chunks_names = [f"{Path(f.system_key).stem}.chunks.jsonl" for f in files]

    filenames2ids = await get_files_names2ids()
    return [filenames2ids[name] for name in chunks_names if name in filenames2ids]


@router.get("/indexes", status_code=200, response_model=IndexesResponse)
async def get_indexes(
    membership: Annotated[OrgMembership, Depends(require_org_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexesResponse:
    result = await db.execute(
        select(OrgIndex)
        .where(OrgIndex.org_id == membership.org_id)
        .order_by(OrgIndex.created_at.desc())
    )
    indexes = result.scalars().all()
    return IndexesResponse(indexes=[IndexRecord.model_validate(i) for i in indexes])


@router.post("/indexes", status_code=201, response_model=IndexRecord)
async def create_index(
    index_request: IndexRequest,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexRecord:
    org_id = membership.org_id

    # 1. Резолвим выбранные файлы в id стора AI Studio ДО создания строки —
    #    если ни один файл не проиндексирован, строить нечего.
    yandex_file_ids = await _resolve_yandex_file_ids(db, index_request.file_ids, org_id)
    if not yandex_file_ids:
        raise HTTPException(
            status_code=400,
            detail="None of the selected files are indexed in Yandex",
        )

    # 2. Durable-строка сразу (status=building): индекс мгновенно виден в списке,
    #    переживает редеплой; довести до ready/failed — работа поллера.
    index = OrgIndex(
        org_id=org_id,
        name=index_request.name,
        status=INDEX_BUILDING,
        source_file_ids=index_request.file_ids,
    )
    db.add(index)
    await db.flush()

    # 3. Запускаем сборку в AI Studio. vector_stores.create возвращает id сразу
    #    (без busy-poll), поэтому запрос не висит на ожидании сборки.
    try:
        vector_store_id = await create_vector_store(index_request.name, yandex_file_ids)
    except Exception as e:
        index.status = INDEX_FAILED
        index.error_message = str(e)
        await db.commit()
        await db.refresh(index)
        return IndexRecord.model_validate(index)

    index.vector_store_id = vector_store_id
    await db.commit()
    await db.refresh(index)
    return IndexRecord.model_validate(index)


@router.delete("/indexes/{index_id}", status_code=204)
async def delete_index_endpoint(
    index_id: int,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    index = await db.get(OrgIndex, index_id)
    if not index or index.org_id != membership.org_id:
        raise HTTPException(status_code=404, detail="Index not found")

    # Удаление строящегося индекса запрещено — ждём ready/failed.
    if index.status == INDEX_BUILDING:
        raise HTTPException(
            status_code=409,
            detail="Index is building; deletion is allowed only after it is ready or failed",
        )

    if index.vector_store_id:
        try:
            await delete_index(index.vector_store_id)
        except Exception as e:
            # Стор мог уже истечь по TTL или быть удалён — строку всё равно чистим.
            print(f"delete_index({index.vector_store_id}) failed: {e}")

    await db.delete(index)
    await db.commit()
    return Response(status_code=204)


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
    # Коммитим до возврата file_id: иначе клиент получает id раньше, чем строка
    # закоммичена, и немедленный PATCH /files/{id}/status ловит 404 (запись ещё
    # не видна другому запросу/сессии).
    await db.commit()

    return UploadLinkResponse(
        upload_url=upload_url,
        s3_key=s3_key,
        file_id=file_id,
        expires_in=PRESIGNED_EXPIRES_IN,
    )
