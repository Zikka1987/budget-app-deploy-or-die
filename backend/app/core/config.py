from pydantic_settings import BaseSettings
from pydantic import Field, computed_field


class Settings(BaseSettings):
    # App
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    app_secret_key: str = Field(default="change-me")

    # Database (direct asyncpg)
    database_url: str = Field(...)
    database_pool_min: int = Field(default=2)
    database_pool_max: int = Field(default=10)

    # Supabase (Auth + Storage only)
    # Auth uses the Supabase JWT signing-key flow: tokens are verified against
    # the project's JWKS document published at
    #   {SUPABASE_URL}/auth/v1/.well-known/jwks.json
    # The legacy SUPABASE_JWT_SECRET (HS256 shared secret) is NOT used.
    supabase_url: str = Field(...)
    supabase_anon_key: str = Field(...)
    supabase_service_role_key: str = Field(...)
    supabase_receipts_bucket: str = Field(default="receipts")

    # JWKS cache tuning. Override SUPABASE_JWKS_URL only if you need to point
    # at a non-standard endpoint; by default it is derived from SUPABASE_URL.
    supabase_jwks_url: str = Field(default="")
    jwks_cache_ttl_seconds: int = Field(default=3600)

    # AI provider
    ocr_provider: str = Field(default="anthropic")
    anthropic_api_key: str = Field(default="")
    ocr_model: str = Field(default="claude-sonnet-4-6")
    ocr_max_tokens: int = Field(default=4096)

    # Categorization threshold: AI suggestions at or above this confidence
    # level no longer trigger per-item manual review. Note: this is a UI
    # hint only; receipts always require user review before posting.
    categorization_confidence_threshold: float = Field(default=0.85)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @computed_field
    @property
    def jwks_url(self) -> str:
        """Full JWKS URL for the Supabase project.

        If SUPABASE_JWKS_URL is set explicitly, use that. Otherwise derive
        from SUPABASE_URL using the standard Supabase path.
        """
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


settings = Settings()
