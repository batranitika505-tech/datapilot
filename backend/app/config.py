from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Optional full database URL (takes precedence over individual DB_* settings)
    DATABASE_URL: str | None = None

    # Individual database credentials
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_HOST: str = "localhost"
    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    DB_NAME: str = "datapilot"

    # Connection pool configuration
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=300)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60, le=86400)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_database_credentials(self):
        if not self.DATABASE_URL and (not self.DB_USER or not self.DB_PASSWORD):
            raise ValueError(
                "Either DATABASE_URL or both DB_USER and DB_PASSWORD must be configured."
            )
        return self


settings = Settings()
