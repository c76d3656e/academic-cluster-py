"""
应用配置管理

使用 pydantic-settings 管理环境变量和配置
"""

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM 配置"""
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096


class EmbeddingSettings(BaseModel):
    """Embedding 配置"""
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: str | None = None
    dimensions: int = 1024


class RerankSettings(BaseModel):
    """Rerank 配置"""
    provider: str = "siliconflow"
    model: str = "BAAI/bge-reranker-v2-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: str | None = None
    threshold: float = 0.02


class RedisSettings(BaseModel):
    """Redis 配置"""
    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0

    @property
    def url(self) -> str:
        """获取 Redis URL"""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class WritingSettings(BaseModel):
    """写作配置"""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_length: int = 50000
    outline_max_sections: int = 10
    outline_max_subsections: int = 5


class Settings(BaseSettings):
    """主配置类"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_env: str = "development"
    app_debug: bool = False  # 安全修复: 默认关闭 debug，避免泄露调试信息
    app_host: str = "0.0.0.0"  # noqa: S104  # nosec B104
    app_port: int = 8000
    app_secret_key: str = "change-me-in-production"

    # CORS 配置（逗号分隔的允许来源列表）
    cors_origins: str | None = None

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "json"

    # LLM 配置（单 provider fallback）
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096

    # LLM 多 provider 配置（JSON 数组，优先于单 provider）
    llm_providers_json: str | None = None

    # Embedding 配置（单 provider fallback）
    embedding_provider: str = "siliconflow"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str | None = None
    embedding_dimensions: int = 1024

    # Embedding 多 provider 配置（JSON 数组）
    embedding_providers_json: str | None = None

    # Rerank 配置（单 provider fallback）
    rerank_provider: str = "siliconflow"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str | None = None
    rerank_threshold: float = 0.02

    # Rerank 多 provider 配置（JSON 数组）
    rerank_providers_json: str | None = None

    # 数据库配置
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "academic_cluster"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    # 向量数据库配置
    vector_db_provider: str = "chromadb"
    vector_db_host: str = "localhost"
    vector_db_port: int = 8000

    # 学术数据源配置
    # Semantic Scholar API key，支持逗号分隔多 key（每个 key 独立 1 rps）
    semantic_scholar_api_key: str | None = None
    pubmed_email: str = "user@example.com"
    pubmed_api_key: str | None = None

    @property
    def semantic_scholar_api_keys(self) -> list[str]:
        """解析多 key（逗号分隔），返回有效 key 列表"""
        if not self.semantic_scholar_api_key:
            return []
        return [k.strip() for k in self.semantic_scholar_api_key.split(",") if k.strip()]

    # 聚类配置
    clustering_algorithm: str = "leiden"
    clustering_resolution: float = 1.0

    # KG 抽取配置
    kg_batch_size: int = 1
    kg_concurrency: int = -1
    evidence_concurrency: int = -1

    # 写作配置
    writing_model: str = "gpt-4o"
    writing_temperature: float = 0.7
    writing_total_target_words: int = 12000

    # Auth 配置
    jwt_secret_key: str = "change-me-jwt-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Provider 加密密钥（Fernet key 或任意密码，程序自动派生）
    provider_encryption_key: str | None = None

    # 默认管理员账户（首次启动时自动创建）
    # admin_password 无默认值，必须通过环境变量或 .env 显式设置
    # 留空则跳过管理员自动创建（开发环境允许，生产环境由 validate_security 强制校验）
    admin_email: str = "admin@cluster.local"
    admin_password: str = ""
    admin_full_name: str = "Administrator"

    # LangGraph 配置
    langgraph_debug: bool = True
    langsmith_api_key: str | None = None
    langsmith_project: str = "academic-cluster"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_security(self) -> None:
        """生产环境安全配置校验，应在应用启动时调用"""
        if not self.is_production:
            return
        insecure_defaults = []
        if self.jwt_secret_key in ("change-me-jwt-secret-in-production", "change-me-in-production"):
            insecure_defaults.append("jwt_secret_key")
        if self.app_secret_key == "change-me-in-production":  # nosec B105
            insecure_defaults.append("app_secret_key")
        if self.postgres_password in ("postgres", ""):
            insecure_defaults.append("postgres_password")
        if not self.admin_password:
            insecure_defaults.append("admin_password (不能为空，必须设置)")
        if insecure_defaults:
            raise RuntimeError(
                f"生产环境检测到不安全的默认配置，请通过环境变量设置: {', '.join(insecure_defaults)}"
            )

    @property
    def embedding(self) -> EmbeddingSettings:
        """获取嵌入配置"""
        return EmbeddingSettings(
            provider=self.embedding_provider,
            model=self.embedding_model,
            api_url=self.embedding_api_url,
            api_key=self.embedding_api_key,
            dimensions=self.embedding_dimensions,
        )

    @property
    def rerank(self) -> RerankSettings:
        """获取重排序配置"""
        return RerankSettings(
            provider=self.rerank_provider,
            model=self.rerank_model,
            api_url=self.rerank_api_url,
            api_key=self.rerank_api_key,
            threshold=self.rerank_threshold,
        )

    @property
    def llm(self) -> LLMSettings:
        """获取 LLM 配置"""
        return LLMSettings(
            provider=self.llm_provider,
            model=self.llm_model,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )

    @property
    def redis(self) -> RedisSettings:
        """获取 Redis 配置"""
        return RedisSettings(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_password,
            db=self.redis_db,
        )

    @property
    def writing(self) -> WritingSettings:
        """获取写作配置"""
        return WritingSettings(
            model=self.writing_model,
            temperature=self.writing_temperature,
        )


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
