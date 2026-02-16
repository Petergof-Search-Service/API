from pydantic import BaseModel


class TaskResponse(BaseModel):
    task_id: str


class StatusResponse(BaseModel):
    status: str


class RagQuestion(BaseModel):
    index: str
    question: str
