"""Application configuration.

Single source of truth for environment-derived settings. Every other
module reads config through `get_settings()` rather than `os.environ`
directly, so tests can override settings by dependency-injecting a
different `Settings` instance instead of mutating process env vars.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "OfferLeaks API"
    app_version: str = "0.1.0"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # --- CORS ---
    # The web app origin(s) allowed to call this API from the browser.
    # Comma-separated in the env var, parsed into a list here.
    cors_origins: str = Field(default="http://localhost:3000")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://offerleaks:offerleaks_dev@localhost:5432/offerleaks"
    )

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton.

    lru_cache keeps this a true singleton per-process while still being
    overridable in tests via FastAPI's dependency_overrides.
    """
    return Settings()
