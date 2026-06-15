"""
管理后台 - 数据源配置管理

管理 Semantic Scholar API Key、PubMed 配置等数据源凭据。
这些配置存储在 .env 中，此端点提供查看和运行时更新能力。
"""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from ..dependencies import require_admin
from ...services.database import DatabaseService, get_database

logger = structlog.get_logger()

router = APIRouter(tags=["admin-source-config"])


# =============================================================================
# 响应模型
# =============================================================================

class SourceConfigItem(BaseModel):
    """数据源配置项"""
    key: str
    label: str
    value: str | None = None
    is_set: bool = False
    description: str = ""


class SourceConfigListResponse(BaseModel):
    """数据源配置列表"""
    configs: list[SourceConfigItem]


class UpdateSourceConfigRequest(BaseModel):
    """更新数据源配置"""
    key: str
    value: str


# =============================================================================
# 端点
# =============================================================================

@router.get("/sources", response_model=SourceConfigListResponse)
async def list_source_configs(
    admin: dict = Depends(require_admin),
):
    """列出所有数据源配置"""
    from ...config import get_settings
    settings = get_settings()

    configs = [
        SourceConfigItem(
            key="semantic_scholar_api_key",
            label="Semantic Scholar API Key",
            value=_mask_key(settings.semantic_scholar_api_key),
            is_set=bool(settings.semantic_scholar_api_key),
            description="支持逗号分隔多 Key（每个 Key 独立 1 rps）",
        ),
        SourceConfigItem(
            key="pubmed_email",
            label="PubMed Email",
            value=settings.pubmed_email,
            is_set=bool(settings.pubmed_email and settings.pubmed_email != "user@example.com"),
            description="NCBI E-utilities 要求的邮箱",
        ),
        SourceConfigItem(
            key="pubmed_api_key",
            label="PubMed API Key",
            value=_mask_key(settings.pubmed_api_key),
            is_set=bool(settings.pubmed_api_key),
            description="NCBI API Key（可选，提高请求速率）",
        ),
        SourceConfigItem(
            key="llm_api_key",
            label="LLM API Key",
            value=_mask_key(settings.llm_api_key),
            is_set=bool(settings.llm_api_key),
            description=f"当前: {settings.llm_provider} / {settings.llm_model}",
        ),
        SourceConfigItem(
            key="embedding_api_key",
            label="Embedding API Key",
            value=_mask_key(settings.embedding_api_key),
            is_set=bool(settings.embedding_api_key),
            description=f"当前: {settings.embedding_provider} / {settings.embedding_model}",
        ),
        SourceConfigItem(
            key="rerank_api_key",
            label="Rerank API Key",
            value=_mask_key(settings.rerank_api_key),
            is_set=bool(settings.rerank_api_key),
            description=f"当前: {settings.rerank_provider} / {settings.rerank_model}",
        ),
    ]

    return SourceConfigListResponse(configs=configs)


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-3:]}"
