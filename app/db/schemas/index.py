from datetime import datetime

from pydantic import BaseModel


class FilesResponse(BaseModel):
    files: list[str]


class IndexRecord(BaseModel):
    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IndexesResponse(BaseModel):
    indexes: list[IndexRecord]


class IndexRequest(BaseModel):
    name: str
    file_names: list[str]


class UploadLinkRequest(BaseModel):
    filename: str


class UploadLinkResponse(BaseModel):
    upload_url: str
    s3_key: str
    file_id: int
    expires_in: int
