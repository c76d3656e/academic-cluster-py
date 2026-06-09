"""
应用配置管理

使用 pydantic-settings 管理环境变量和配置
"""

from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM 配置"""
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096


class EmbeddingSettings(BaseModel):
    """Embedding 配置"""
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: Optional[str] = None
    dimensions: int = 1024


class RerankSettings(BaseModel):
    """Rerank 配置"""
    provider: str = "siliconflow"
    model: str = "BAAI/bge-reranker-v2-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: Optional[str] = None
    threshold: float = 0.02


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

    # LLM 配置
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096

    # Embedding 配置
    embedding_provider: str = "siliconflow"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: Optional[str] = None
    embedding_dimensions: int = 1024

    # Rerank 配置
    rerank_provider: str = "siliconflow"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: Optional[str] = None
    rerank_threshold: float = 0.02

    # 数据库配置
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "academic_cluster"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0

    # 向量数据库配置
    vector_db_provider: str = "chromadb"
    vector_db_host: str = "localhost"
    vector_db_port: int = 8000

    # 学术数据源配置
    semantic_scholar_api_key: Optional[str] = None
    pubmed_email: str = "user@example.com"
    pubmed_api_key: Optional[str] = None

    # 聚类配置
    clustering_algorithm: str = "leiden"
    clustering_resolution: float = 1.0

    # 写作配置
    writing_model: str = "gpt-4o"
    writing_temperature: float = 0.7

    # LangGraph 配置
    langgraph_debug: bool = True
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "academic-cluster"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

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


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
