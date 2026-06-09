"""
应用配置管理

使用 pydantic-settings 管理环境变量和配置
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """LLM 配置"""
    model_config = SettingsConfigDict(env_prefix="LLM_")

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096


class EmbeddingSettings(BaseSettings):
    """Embedding 配置"""
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: Optional[str] = None
    dimensions: int = 1024


class RerankSettings(BaseSettings):
    """Rerank 配置"""
    model_config = SettingsConfigDict(env_prefix="RERANK_")

    provider: str = "siliconflow"
    model: str = "BAAI/bge-reranker-v2-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: Optional[str] = None
    threshold: float = 0.02


class DatabaseSettings(BaseSettings):
    """数据库配置"""
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    db: str = "academic_cluster"
    user: str = "postgres"
    password: str = "postgres"

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @property
    def sync_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class RedisSettings(BaseSettings):
    """Redis 配置"""
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class VectorDBSettings(BaseSettings):
    """向量数据库配置"""
    model_config = SettingsConfigDict(env_prefix="VECTOR_DB_")

    provider: str = "chromadb"
    host: str = "localhost"
    port: int = 8000
    api_key: Optional[str] = None


class AcademicSourceSettings(BaseSettings):
    """学术数据源配置"""
    model_config = SettingsConfigDict(env_prefix="")

    semantic_scholar_api_key: Optional[str] = None
    semantic_scholar_rate_limit: int = 1

    pubmed_email: str = "user@example.com"
    pubmed_tool: str = "AcademicReviewStudio"
    pubmed_api_key: Optional[str] = None
    pubmed_rate_limit: int = 10

    arxiv_rate_limit: int = 3
    arxiv_max_results: int = 100


class ClusteringSettings(BaseSettings):
    """聚类配置"""
    model_config = SettingsConfigDict(env_prefix="CLUSTERING_")

    algorithm: str = "leiden"
    resolution: float = 1.0
    min_cluster_size: int = 5
    max_clusters: int = 50


class WritingSettings(BaseSettings):
    """写作配置"""
    model_config = SettingsConfigDict(env_prefix="WRITING_")

    model: str = "gpt-4o"
    temperature: float = 0.7
    max_length: int = 50000
    outline_max_sections: int = 10
    outline_max_subsections: int = 5


class PipelineSettings(BaseSettings):
    """Pipeline 配置"""
    model_config = SettingsConfigDict(env_prefix="PIPELINE_")

    max_embedding_papers: int = 500
    core_reference_count: int = 80
    auxiliary_reference_count: int = 160
    rerank_batch_size: int = 25
    kg_batch_size: int = 16


class LangSmithSettings(BaseSettings):
    """LangSmith 配置"""
    model_config = SettingsConfigDict(env_prefix="LANGSMITH_")

    api_key: Optional[str] = None
    project: str = "academic-cluster"
    endpoint: str = "https://api.smith.langchain.com"
    tracing_v2: bool = True


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
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "change-me-in-production"

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "json"

    # 子配置
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = Field(default_factory=RerankSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    academic_sources: AcademicSourceSettings = Field(default_factory=AcademicSourceSettings)
    clustering: ClusteringSettings = Field(default_factory=ClusteringSettings)
    writing: WritingSettings = Field(default_factory=WritingSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    langsmith: LangSmithSettings = Field(default_factory=LangSmithSettings)

    # LangGraph 配置
    langgraph_debug: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
