"""
数据库服务

提供 PostgreSQL 异步数据库访问。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

from ..config import get_settings

logger = structlog.get_logger()


class DatabaseService:
    """PostgreSQL 异步数据库服务"""

    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()

        if database_url is None:
            database_url = settings.database.url

        self.engine = create_async_engine(
            database_url,
            echo=settings.app_debug,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
        )

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("Database service initialized", url=database_url.split("@")[-1])

    async def close(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("Database connection closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话"""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def execute(self, query, params=None):
        """执行查询"""
        async with self.session() as session:
            result = await session.execute(query, params)
            return result

    async def save_paper(self, paper_data: dict) -> str:
        """保存论文到数据库"""
        # TODO: 实现论文保存
        # 这是一个占位实现
        paper_id = paper_data.get("id")
        logger.info("Saving paper", paper_id=paper_id)
        return paper_id

    async def get_paper(self, paper_id: str) -> Optional[dict]:
        """获取论文详情"""
        # TODO: 实现论文查询
        logger.info("Getting paper", paper_id=paper_id)
        return None

    async def save_papers_batch(self, papers: list[dict]) -> list[str]:
        """批量保存论文"""
        # TODO: 实现批量保存
        paper_ids = [p.get("id") for p in papers]
        logger.info("Saving papers batch", count=len(paper_ids))
        return paper_ids

    async def get_papers_by_ids(self, paper_ids: list[str]) -> list[dict]:
        """批量获取论文"""
        # TODO: 实现批量查询
        logger.info("Getting papers by IDs", count=len(paper_ids))
        return []

    async def save_embedding(self, paper_id: str, embedding: list[float], model_name: str) -> str:
        """保存嵌入向量"""
        # TODO: 实现嵌入保存
        embedding_id = f"emb_{paper_id}_{model_name}"
        logger.info("Saving embedding", paper_id=paper_id, model=model_name)
        return embedding_id

    async def save_cluster(self, cluster_data: dict) -> str:
        """保存聚类结果"""
        # TODO: 实现聚类保存
        cluster_id = cluster_data.get("id")
        logger.info("Saving cluster", cluster_id=cluster_id)
        return cluster_id

    async def save_kg_entities(self, entities: list[dict]) -> list[str]:
        """保存知识图谱实体"""
        # TODO: 实现实体保存
        entity_ids = [e.get("id") for e in entities]
        logger.info("Saving KG entities", count=len(entity_ids))
        return entity_ids

    async def save_kg_relations(self, relations: list[dict]) -> list[str]:
        """保存知识图谱关系"""
        # TODO: 实现关系保存
        relation_ids = [r.get("id") for r in relations]
        logger.info("Saving KG relations", count=len(relation_ids))
        return relation_ids

    async def save_evidence_card(self, card_data: dict) -> str:
        """保存证据卡片"""
        # TODO: 实现证据卡片保存
        card_id = card_data.get("id")
        logger.info("Saving evidence card", card_id=card_id)
        return card_id

    async def save_outline(self, outline_data: dict) -> str:
        """保存大纲"""
        # TODO: 实现大纲保存
        outline_id = outline_data.get("id")
        logger.info("Saving outline", outline_id=outline_id)
        return outline_id

    async def save_written_section(self, section_data: dict) -> str:
        """保存已写章节"""
        # TODO: 实现章节保存
        section_id = section_data.get("id")
        logger.info("Saving written section", section_id=section_id)
        return section_id

    async def save_artifact(self, artifact_data: dict) -> str:
        """保存产出物"""
        # TODO: 实现产出物保存
        artifact_id = artifact_data.get("id")
        logger.info("Saving artifact", artifact_id=artifact_id)
        return artifact_id


# 全局数据库实例
_db_service: Optional[DatabaseService] = None


def get_database() -> DatabaseService:
    """获取数据库服务单例"""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
    return _db_service


async def close_database():
    """关闭数据库连接"""
    global _db_service
    if _db_service is not None:
        await _db_service.close()
        _db_service = None
