from datetime import datetime

from pydantic import BaseModel


class RagFileRecord(BaseModel):
    id: int
    name: str


class FilesResponse(BaseModel):
    files: list[RagFileRecord]


class IndexRecord(BaseModel):
    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IndexesResponse(BaseModel):
    indexes: list[IndexRecord]


class IndexRequest(BaseModel):
    name: str
    file_ids: list[int]


class UploadLinkRequest(BaseModel):
    filename: str


class UploadLinkResponse(BaseModel):
    upload_url: str
    s3_key: str
    file_id: int
    expires_in: int
