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
    # FlareSolverr endpoint (e.g. http://127.0.0.1:8191/v1) — only needed
    # when GasBuddy's Cloudflare protection blocks the deploy's own IP
    # (common from a datacenter/cloud IP, not from a home connection).
    # Empty means py-gasbuddy talks to GasBuddy directly, unchanged.
    gasbuddy_solver_url: str = ""
    # py-gasbuddy's own default (60000) is also what it tells FlareSolverr
    # as `maxTimeout` — confirmed live that a harder/slower Cloudflare
    # challenge can genuinely need more than 60s to solve, timing out
    # here even though FlareSolverr's Chrome was still actively working
    # on it. Must be paired with raising FlareSolverr's own BROWSER_TIMEOUT
    # env var to at least this value on its own deploy — this setting
    # alone doesn't help if FlareSolverr's own cap is still lower.
    gasbuddy_timeout_ms: int = 120000
    # Render API credentials for restarting the FlareSolverr service on
    # app-launch warmup — confirmed live that a fresh restart (not just
    # waking an already-running container) can succeed where a merely-
    # awake one keeps failing, plausibly because FlareSolverr's browser
    # automation accumulates memory/process cruft over many requests.
    # Both empty means warmup falls back to just pinging the container's
    # existing health check without restarting it.
    render_api_key: str = ""
    flaresolverr_service_id: str = ""
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
