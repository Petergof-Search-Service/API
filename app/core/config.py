from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    DATABASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    S3_BUCKET_NAME: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_ENDPOINT_URL: str = "https://storage.yandexcloud.net"

    CLOUD_FUNCTION_API_KEY: str

    # Поллер статуса сборки индексов (см. app/core/index_poller.py)
    INDEX_POLL_INTERVAL_SECONDS: int = 5
    INDEX_POLL_BATCH: int = 20
    # Сборка идёт минуты—часы; по превышении билд помечается failed.
    INDEX_BUILD_TIMEOUT_SECONDS: int = 10800  # 3 часа
    # building-строка без vector_store_id старше этого = create не завершился (сбой) → failed.
    INDEX_STALE_CREATE_SECONDS: int = 120


settings = Settings()
