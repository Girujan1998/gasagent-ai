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
    gemini_api_key: str = ""
    # Kept configurable rather than hardcoded — the available models and
    # their free-tier quotas change over time (confirmed live:
    # gemini-2.5-flash, an earlier default here, is no longer offered to
    # new users at all; gemini-3.6-flash, the default after that, turned
    # out to have a free tier of just 20 requests/day — gemini-3.5-flash-
    # lite's free tier is meaningfully more generous), and swapping one
    # shouldn't need a code change.
    gemini_model: str = "gemini-3.5-flash-lite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
