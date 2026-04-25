from datetime import datetime

from pydantic import BaseModel


class FileRecord(BaseModel):
    id: int
    original_filename: str
    display_name: str | None
    system_key: str
    s3_url: str
    status: str
    error_message: str | None
    status_changed_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    files: list[FileRecord]


class StatusUpdate(BaseModel):
    status: str
    error_message: str | None = None


class ServiceStatusUpdate(BaseModel):
    system_key: str
    status: str
    error_message: str | None = None
