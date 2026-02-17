import re

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    RAG_YANDEX_API_KEY: str
    RAG_YANDEX_FOLDER_ID: str
    RAG_ACCESS_KEY: str
    RAG_SECRET_KEY: str
    RAG_YANDEX_CLOUD_MODEL: str = "aliceai-llm/latest"
    RAG_BUCKET_NAME: str = "markup-baket"
    RAG_S3_ENDPOINT_URL: str = "https://storage.yandexcloud.net"
    RAG_CHUNKS_PATH: str = "data/chunks"
    RAG_MAX_CHUNK_LEN: int = 8000
    RAG_PAGE_MARK_RE: re.Pattern[str] = re.compile(r"\[PAGE\s+(\d+)\]")
    RAG_PAGE_MARK_REMOVE_RE: re.Pattern[str] = re.compile(r"\s*\[PAGE\s+\d+\]\s*\n?")


settings = Settings()
