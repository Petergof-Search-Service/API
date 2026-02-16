from pydantic import BaseModel


class Review(BaseModel):
    question: str
    model_answer: str
    is_ok: bool
    correct_answer: str | None = None
