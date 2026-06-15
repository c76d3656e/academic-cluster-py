"""
Pipeline 配置管理 API

提供 pipeline 各阶段的可调参数管理，支持热重载。
参数存储在数据库中，pipeline 运行时实时读取。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import get_database

router = APIRouter(prefix="/pipeline-config")

# =============================================================================
# 默认配置（与 .env / settings.py 对齐）
# =============================================================================

DEFAULT_CONFIG = {
    # 搜索阶段
    "search.limit_per_source": {
        "value": "200",
        "label": "每源最大搜索数",
        "description": "每个数据源（Semantic Scholar, OpenAlex, Crossref, arXiv, PubMed）的最大搜索结果数",
        "group": "搜索",
        "type": "int",
    },
    "search.max_rounds": {
        "value": "3",
        "label": "最大搜索轮次",
        "description": "多轮搜索的最大轮数，每轮根据覆盖度评估决定是否补充搜索",
        "group": "搜索",
        "type": "int",
    },
    "search.initial_query_limit": {
        "value": "12",
        "label": "初始搜索词上限",
        "description": "LLM 生成的初始搜索 query 最大数量",
        "group": "搜索",
        "type": "int",
    },
    "search.refine_query_limit": {
        "value": "8",
        "label": "补充搜索词上限",
        "description": "每轮补充搜索时 LLM 生成的新 query 最大数量",
        "group": "搜索",
        "type": "int",
    },
    "search.target_relevant": {
        "value": "50",
        "label": "目标相关论文数",
        "description": "覆盖度评估认为充分的最低相关论文数",
        "group": "搜索",
        "type": "int",
    },
    "search.min_relevant": {
        "value": "20",
        "label": "最少相关论文数",
        "description": "低于此数量则搜索失败警告",
        "group": "搜索",
        "type": "int",
    },
    "search.sources": {
        "value": "semantic_scholar,openalex,crossref,arxiv,pubmed",
        "label": "数据源列表",
        "description": "要搜索的学术数据源，逗号分隔",
        "group": "搜索",
        "type": "string",
    },

    # 过滤阶段
    "filter.min_citation_count": {
        "value": "0",
        "label": "最小引用数",
        "description": "过滤掉引用数低于此值的论文",
        "group": "过滤",
        "type": "int",
    },
    "filter.require_abstract": {
        "value": "true",
        "label": "要求有摘要",
        "description": "是否过滤掉没有摘要的论文",
        "group": "过滤",
        "type": "bool",
    },

    # BM25 阶段
    "bm25.min_score": {
        "value": "0.5",
        "label": "BM25 最低分数",
        "description": "BM25 评分低于此阈值的论文将被过滤，分数范围取决于语料库大小",
        "group": "过滤",
        "type": "float",
    },
    "bm25.max_papers": {
        "value": "2000",
        "label": "BM25 最大论文数",
        "description": "BM25 筛选后进入 embedding 的最大论文数上限",
        "group": "过滤",
        "type": "int",
    },

    # 嵌入阶段
    "embedding.max_papers": {
        "value": "1000",
        "label": "最大嵌入论文数",
        "description": "进入 embedding 的最大论文数上限，从 BM25 结果中选取",
        "group": "嵌入",
        "type": "int",
    },

    # 重排序阶段
    "rerank.max_papers": {
        "value": "500",
        "label": "重排序最大论文数",
        "description": "rerank 后保留的高质量论文数，进入 KG 抽取和聚类",
        "group": "重排序",
        "type": "int",
    },
    "rerank.core_count": {
        "value": "160",
        "label": "核心参考文献数",
        "description": "聚类后选取的核心论文数量（用于 evidence cards）",
        "group": "重排序",
        "type": "int",
    },
    "rerank.auxiliary_count": {
        "value": "160",
        "label": "辅助参考文献数",
        "description": "聚类后选取的辅助论文数量（用于 review 写作）",
        "group": "重排序",
        "type": "int",
    },

    # 聚类阶段
    "kg.concurrency": {
        "value": "-1",
        "label": "\u004b\u0047 \u5e76\u53d1\u5ea6",
        "description": "\u002d\u0031 \u8868\u793a\u81ea\u52a8\uff1a\u6309\u5df2\u542f\u7528 \u004c\u004c\u004d \u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u7684 \u0072\u0070\u006d\u005f\u006c\u0069\u006d\u0069\u0074 \u603b\u548c\u8bbe\u7f6e\u5e76\u53d1\uff1b\u6b63\u6574\u6570\u8868\u793a\u624b\u52a8\u4e0a\u9650\u3002",
        "group": "\u004b\u0047 \u62bd\u53d6",
        "type": "int",
    },
    "evidence.concurrency": {
        "value": "-1",
        "label": "Evidence card 并发度",
        "description": "-1 表示自动：按已启用 LLM provider 的 rpm_limit 总和设置并发；正整数表示手动上限。",
        "group": "证据卡片",
        "type": "int",
    },

    "clustering.algorithm": {
        "value": "leiden",
        "label": "社区检测算法",
        "description": "可选 leiden（默认，modularity 优化）或 walktrap（随机游走）",
        "group": "聚类",
        "type": "string",
    },
    "clustering.resolution": {
        "value": "1.0",
        "label": "Leiden 分辨率",
        "description": "Leiden 社区检测的 resolution 参数，越大聚类越多越细",
        "group": "聚类",
        "type": "float",
    },
    "clustering.weight_knn": {
        "value": "0.45",
        "label": "KNN 边权重",
        "description": "向量相似度边在混合图中的权重",
        "group": "聚类",
        "type": "float",
    },
    "clustering.weight_kg_relation": {
        "value": "0.25",
        "label": "KG 关系边权重",
        "description": "知识图谱关系边在混合图中的权重",
        "group": "聚类",
        "type": "float",
    },
    "clustering.weight_shared_entity": {
        "value": "0.15",
        "label": "共享实体边权重",
        "description": "共享 KG 实体边在混合图中的权重",
        "group": "聚类",
        "type": "float",
    },
    "clustering.weight_evidence": {
        "value": "0.10",
        "label": "证据边权重",
        "description": "共享证据卡片边在混合图中的权重",
        "group": "聚类",
        "type": "float",
    },
    "clustering.weight_quality": {
        "value": "0.05",
        "label": "质量先验边权重",
        "description": "高质量论文对边在混合图中的权重",
        "group": "聚类",
        "type": "float",
    },

    # 写作阶段
    "writing.total_target_words": {
        "value": "12000",
        "label": "综述目标字数",
        "description": "综述全文的目标字数",
        "group": "写作",
        "type": "int",
    },
    "writing.section_reference_target": {
        "value": "30",
        "label": "每章参考文献数",
        "description": "每个章节分配的候选参考文献上限",
        "group": "写作",
        "type": "int",
    },
}


# =============================================================================
# 数据库初始化
# =============================================================================

async def init_pipeline_config_table():
    """创建 pipeline_config 表（如果不存在）"""
    db = get_database()
    async with db.session() as session:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL,
                label VARCHAR(200) NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                group_name VARCHAR(50) NOT NULL DEFAULT 'general',
                value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await session.commit()


async def _ensure_defaults():
    """确保默认配置项存在"""
    db = get_database()
    async with db.session() as session:
        for key, cfg in DEFAULT_CONFIG.items():
            await session.execute(text("""
                INSERT INTO pipeline_config (key, value, label, description, group_name, value_type)
                VALUES (:key, :value, :label, :desc, :group, :vtype)
                ON CONFLICT (key) DO NOTHING
            """), {
                "key": key,
                "value": cfg["value"],
                "label": cfg["label"],
                "desc": cfg["description"],
                "group": cfg["group"],
                "vtype": cfg["type"],
            })
        await session.execute(text("""
            UPDATE pipeline_config
            SET value = '160', updated_at = NOW()
            WHERE key = 'rerank.core_count' AND value = '80'
        """))
        await session.commit()


# =============================================================================
# 读取配置
# =============================================================================

async def get_pipeline_config_dict() -> dict[str, str]:
    """读取所有 pipeline 配置为 dict"""
    db = get_database()
    async with db.session() as session:
        result = await session.execute(text("SELECT key, value FROM pipeline_config"))
        rows = result.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_pipeline_config_value(key: str, default: str = "") -> str:
    """读取单个配置值"""
    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT value FROM pipeline_config WHERE key = :key"),
            {"key": key},
        )
        row = result.fetchone()
    return row[0] if row else default


def build_node_config(raw: dict[str, str]) -> dict:
    """
    将扁平的 key-value 配置转换为各节点读取的 config dict。

    返回的 dict 可直接传入 PipelineState.config。
    """
    def _int(key: str, default: int) -> int:
        v = raw.get(key, str(default))
        try:
            return int(v)
        except (ValueError, TypeError):
            return default

    def _float(key: str, default: float) -> float:
        v = raw.get(key, str(default))
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def _bool(key: str, default: bool) -> bool:
        v = raw.get(key, str(default)).lower()
        return v in ("true", "1", "yes")

    def _list(key: str, default: list[str]) -> list[str]:
        v = raw.get(key, "")
        if not v:
            return default
        return [s.strip() for s in v.split(",") if s.strip()]

    return {
        # search
        "limit_per_source": _int("search.limit_per_source", 200),
        "sources": _list("search.sources", ["semantic_scholar", "openalex", "crossref", "arxiv", "pubmed"]),
        "search.max_rounds": _int("search.max_rounds", 3),
        "search.initial_query_limit": _int("search.initial_query_limit", 12),
        "search.refine_query_limit": _int("search.refine_query_limit", 8),
        "search.target_relevant": _int("search.target_relevant", 50),
        "search.min_relevant": _int("search.min_relevant", 20),

        # filter
        "min_citation_count": _int("filter.min_citation_count", 0),
        "require_abstract": _bool("filter.require_abstract", True),

        # bm25
        "bm25.min_score": _float("bm25.min_score", 0.5),
        "bm25.max_papers": _int("bm25.max_papers", 2000),

        # embedding
        "max_embedding_papers": _int("embedding.max_papers", 1000),

        # rerank
        "rerank.max_papers": _int("rerank.max_papers", 500),
        "core_reference_count": _int("rerank.core_count", 160),
        "auxiliary_reference_count": _int("rerank.auxiliary_count", 160),

        # kg
        "kg_concurrency": _int("kg.concurrency", -1),
        "evidence_concurrency": _int("evidence.concurrency", -1),

        # clustering
        "clustering_algorithm": raw.get("clustering.algorithm", "leiden"),
        "clustering_resolution": _float("clustering.resolution", 1.0),
        "hybrid_graph_weights": {
            "knn": _float("clustering.weight_knn", 0.45),
            "kg_relation": _float("clustering.weight_kg_relation", 0.25),
            "shared_entity": _float("clustering.weight_shared_entity", 0.15),
            "evidence": _float("clustering.weight_evidence", 0.10),
            "quality": _float("clustering.weight_quality", 0.05),
        },

        # writing
        "total_target_words": _int("writing.total_target_words", 12000),
        "section_reference_target": _int("writing.section_reference_target", 30),
    }


# =============================================================================
# API 路由
# =============================================================================

class PipelineConfigItem(BaseModel):
    key: str
    value: str
    label: str = ""
    description: str = ""
    group: str = ""
    type: str = "string"


class PipelineConfigUpdate(BaseModel):
    value: str


@router.get("", response_model=list[PipelineConfigItem])
async def list_pipeline_config():
    """获取所有 pipeline 配置"""
    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        result = await session.execute(text(
            "SELECT key, value, label, description, group_name, value_type "
            "FROM pipeline_config ORDER BY group_name, key"
        ))
        rows = result.fetchall()

    return [
        PipelineConfigItem(
            key=row[0], value=row[1], label=row[2],
            description=row[3], group=row[4], type=row[5],
        )
        for row in rows
    ]


@router.put("/{key}")
async def update_pipeline_config(key: str, body: PipelineConfigUpdate):
    """更新单个 pipeline 配置"""
    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT key FROM pipeline_config WHERE key = :key"),
            {"key": key},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

        await session.execute(
            text("UPDATE pipeline_config SET value = :value, updated_at = NOW() WHERE key = :key"),
            {"key": key, "value": body.value},
        )
        await session.commit()

    return {"key": key, "value": body.value, "message": "配置已更新，新 pipeline 运行时生效"}


@router.post("/reset")
async def reset_pipeline_config():
    """重置所有 pipeline 配置为默认值"""
    db = get_database()
    async with db.session() as session:
        for key, cfg in DEFAULT_CONFIG.items():
            await session.execute(
                text("UPDATE pipeline_config SET value = :value, updated_at = NOW() WHERE key = :key"),
                {"key": key, "value": cfg["value"]},
            )
        await session.commit()

    return {"message": "所有配置已重置为默认值"}
