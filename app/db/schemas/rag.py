from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str


class RagQuestion(BaseModel):
    index: str
    question: str


class AnswerResponse(BaseModel):
    answer: str
    context: str
