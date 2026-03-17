from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    firebase_project_id: str
    firebase_private_key: str
    firebase_client_email: str
    gemini_api_key: str
    telegram_bot_token: str = ""
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
