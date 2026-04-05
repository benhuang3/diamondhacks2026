"""Application settings loaded from environment / .env.

This file is LOCKED by CONTRACTS.md §4. Do not change field names or defaults
without coordinating with Agent A (backend).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-6"

    # DB
    database_url: str = "sqlite+aiosqlite:///./storefront.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,chrome-extension://*"

    # Browser Use
    browser_use_api_key: str = ""
    browser_use_headless: bool = True
    browser_use_timeout_ms: int = 30000
    max_scan_pages: int = 5
    max_competitors: int = 5

    log_level: str = "INFO"

    # Force demo mode regardless of ANTHROPIC_API_KEY.
    demo_mode: bool = False


settings = Settings()
