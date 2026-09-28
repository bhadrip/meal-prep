from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

MCP_AUTH_SCOPES = ("openid", "email", "offline_access")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_base_url: str = "http://localhost:8000"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    auth_required: bool = False
    demo_user_id: str = "00000000-0000-0000-0000-000000000001"
    demo_household_id: str = "00000000-0000-0000-0000-000000000010"

    @property
    def supabase_auth_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def mcp_resource_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/mcp"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
