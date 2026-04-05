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
    # Each competitor drives a full browser-use cloud checkout walk
    # (~60-90s, paid tokens). The live flow compares the target store
    # against the first N competitors that successfully reach their cart
    # pages; remaining candidates in the pool are cancelled once N is hit.
    max_competitors: int = 3
    # LLM the browser-use cloud task uses to drive navigation. Picked from
    # browser-use's model catalog; "browser-use-2.0" is their tuned default.
    browser_use_cloud_model: str = "browser-use-2.0"
    # When set, competitor cart walks on detected Shopify stores replay
    # this pre-recorded skill (deterministic clicks, no LLM planning →
    # ~$0 marginal cost vs. the full agent loop). Create a skill via
    # browser-use dashboard or SDK, then paste its id here.
    shopify_skill_id: str = ""
    # When true, run competitor discovery through a browser-use cloud
    # agent that actually searches + verifies URLs (streaming reasoning).
    # Default False — the live flow uses Claude to pick the top 2 most
    # similar storefronts (fast + cheap) and then browser-use scrapes them.
    competitor_discovery_via_agent: bool = False

    log_level: str = "INFO"
    # File logging: when log_file is set, INFO+ goes to a rotating file
    # and WARNING+ also echoes to stderr so critical events stay visible
    # in the terminal. Set log_file="" to go back to stdout only.
    log_file: str = "logs/backend.log"
    log_file_max_bytes: int = 10_000_000
    log_file_backup_count: int = 3

    # Force demo mode regardless of ANTHROPIC_API_KEY.
    demo_mode: bool = False

    # Rate limits (per client IP, per 60s window). These protect the
    # Anthropic/BrowserUse cost surface on unauthenticated POST endpoints.
    rate_limit_scan_per_min: int = 10
    rate_limit_competitors_per_min: int = 10
    # Per-scan fix-generation budget (keyed on scan_id, not client IP).
    rate_limit_fix_per_min: int = 20
    # Memory cap for the rate limiter: at most this many distinct
    # (method,path,client_ip) buckets are kept; oldest evicted when full.
    rate_limit_max_buckets: int = 10_000
    # When true, use the left-most X-Forwarded-For entry as the client IP
    # (only safe behind a trusted reverse proxy).
    trust_forwarded_for: bool = False

    # Install a process-wide getaddrinfo filter that drops private/loopback
    # IPs. Defense in depth against DNS rebinding and redirect SSRF.
    ssrf_egress_guard: bool = True


settings = Settings()
