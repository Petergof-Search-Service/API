from datetime import datetime

from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str


class RagQuestion(BaseModel):
    index: str
    question: str


class AnswerResponse(BaseModel):
    answer: str
    context: str


class HistoryMessage(BaseModel):
    id: int
    role: str
    content: str
    context: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]
