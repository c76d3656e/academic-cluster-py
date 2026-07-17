"""Environment-backed application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import quote, urlsplit

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseModel):
    """Redis connection settings consumed by the cache service."""

    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0

    @property
    def url(self) -> str:
        auth = f":{quote(self.password, safe='')}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


def _is_placeholder(value: str | None, *, minimum_length: int = 1) -> bool:
    if value is None or len(value.strip()) < minimum_length:
        return True
    normalized = value.strip().casefold()
    return (
        normalized.startswith("your_")
        or normalized.startswith("change-me")
        or "placeholder" in normalized
        or normalized in {"postgres", "password", "secret", "changeme"}
        or (normalized.startswith("<") and normalized.endswith(">"))
    )


class Settings(BaseSettings):
    """Runtime settings with production fail-fast validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_debug: bool = False
    cors_origins: str | None = None
    log_level: str = "INFO"

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_providers_json: str | None = None

    embedding_provider: str = "siliconflow"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str | None = None
    embedding_providers_json: str | None = None

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "academic_cluster"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    semantic_scholar_api_key: str | None = None
    pubmed_email: str = "user@example.com"
    pubmed_api_key: str | None = None

    jwt_secret_key: str = "change-me-jwt-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    provider_encryption_key: str | None = None

    admin_email: str = "admin@cluster.local"
    admin_password: str = ""
    admin_full_name: str = "Administrator"

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() == "production"

    @property
    def redis(self) -> RedisSettings:
        return RedisSettings(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_password,
            db=self.redis_db,
        )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse current CSV and legacy JSON-array CORS formats."""

        raw = (self.cors_origins or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [
                    item.strip()
                    for item in parsed
                    if isinstance(item, str) and item.strip()
                ]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def _provider_json_is_insecure(self, raw: str | None) -> bool:
        if not raw:
            return False
        try:
            providers = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return True
        if not isinstance(providers, list):
            return True
        return any(
            not isinstance(provider, dict)
            or _is_placeholder(str(provider.get("api_key") or ""), minimum_length=8)
            for provider in providers
        )

    def validate_security(self) -> None:
        """Reject unstable, missing, or public-placeholder production secrets."""

        if not self.is_production:
            return

        insecure: list[str] = []
        if _is_placeholder(self.jwt_secret_key, minimum_length=32):
            insecure.append("jwt_secret_key")
        if _is_placeholder(self.postgres_password, minimum_length=12):
            insecure.append("postgres_password")
        if _is_placeholder(self.redis_password, minimum_length=12):
            insecure.append("redis_password")
        if _is_placeholder(self.admin_password, minimum_length=12):
            insecure.append("admin_password")
        if _is_placeholder(self.provider_encryption_key, minimum_length=32):
            insecure.append("provider_encryption_key")
        if self.app_debug:
            insecure.append("app_debug")
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            insecure.append("jwt_algorithm")
        origins = self.cors_origin_list
        if "*" in origins:
            insecure.append("cors_origins")
        if self.cors_origins and (
            not origins
            or any(
                origin != "*"
                and (
                    (parts := urlsplit(origin)).scheme not in {"http", "https"}
                    or not parts.netloc
                    or parts.path not in {"", "/"}
                    or bool(parts.query or parts.fragment)
                )
                for origin in origins
            )
        ):
            insecure.append("cors_origins")
        if self.llm_api_key and _is_placeholder(self.llm_api_key, minimum_length=8):
            insecure.append("llm_api_key")
        if self.embedding_api_key and _is_placeholder(
            self.embedding_api_key, minimum_length=8
        ):
            insecure.append("embedding_api_key")
        if self._provider_json_is_insecure(self.llm_providers_json):
            insecure.append("llm_providers_json")
        if self._provider_json_is_insecure(self.embedding_providers_json):
            insecure.append("embedding_providers_json")

        if insecure:
            names = ", ".join(insecure)
            raise RuntimeError(
                "Production configuration contains missing, weak, or placeholder "
                f"secrets: {names}"
            )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
