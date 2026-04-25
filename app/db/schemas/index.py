from pydantic import BaseModel


class FilesResponse(BaseModel):
    files: list[str]


class IndexesResponse(BaseModel):
    indexes: list[str]


class IndexRequest(BaseModel):
    name: str
    file_names: list[str]


class RagQuestion(BaseModel):
    question: str


class UploadLinkRequest(BaseModel):
    filename: str


class UploadLinkResponse(BaseModel):
    upload_url: str
    s3_key: str
    file_id: int
    expires_in: int
