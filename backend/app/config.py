from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GasAgent.ai API"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]
    nrel_api_key: str = ""
    ocm_api_key: str = ""
    eia_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
