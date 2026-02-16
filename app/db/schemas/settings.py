from pydantic import BaseModel


class SettingModel(BaseModel):
    prompt: str
    temperature: float
    count_vector: int
    count_fulltext: int
