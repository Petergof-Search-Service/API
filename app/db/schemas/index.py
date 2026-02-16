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


class OcrStatusResponse(BaseModel):
    is_running: bool
