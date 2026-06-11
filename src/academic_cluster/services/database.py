"""
数据库服务

提供 PostgreSQL 异步数据库访问，使用 pgvector 进行向量存储。
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional
import json
import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)


def _convert_uuid_fields(row: dict) -> dict:
    """将 UUID 字段转换为字符串"""
    result = {}
    for key, value in row.items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif hasattr(value, '__class__') and 'UUID' in value.__class__.__name__:
            result[key] = str(value)
        else:
            result[key] = value
    return result

from ..config import get_settings

logger = structlog.get_logger()


class DatabaseService:
    """PostgreSQL 异步数据库服务"""

    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()

        if database_url is None:
            database_url = (
                f"postgresql+asyncpg://{settings.postgres_user}:"
                f"{settings.postgres_password}@{settings.postgres_host}:"
                f"{settings.postgres_port}/{settings.postgres_db}"
            )

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

        logger.info("Database service initialized")

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

    async def save_paper(self, paper_data: dict) -> str:
        """保存论文到数据库，返回数据库中实际的 paper_id"""
        paper_id = paper_data.get("id", str(uuid.uuid4()))

        # Convert JSONB fields to JSON strings
        authors = paper_data.get("authors")
        if isinstance(authors, list):
            authors = json.dumps(authors)

        fields_of_study = paper_data.get("fields_of_study")
        if isinstance(fields_of_study, list):
            fields_of_study = json.dumps(fields_of_study)

        metadata = paper_data.get("metadata")
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata)

        # Parse publication_date string to date object
        publication_date = paper_data.get("publication_date")
        if isinstance(publication_date, str):
            try:
                publication_date = datetime.fromisoformat(publication_date.replace("Z", "+00:00")).date()
            except ValueError:
                publication_date = None

        async with self.session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO papers (id, external_id, source, title, abstract, authors,
                                      publication_date, journal, doi, url, pdf_url,
                                      citation_count, reference_count, fields_of_study, metadata)
                    VALUES (:id, :external_id, :source, :title, :abstract, CAST(:authors AS jsonb),
                            :publication_date, :journal, :doi, :url, :pdf_url,
                            :citation_count, :reference_count, CAST(:fields_of_study AS jsonb), CAST(:metadata AS jsonb))
                    ON CONFLICT (external_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        abstract = EXCLUDED.abstract,
                        citation_count = EXCLUDED.citation_count
                    RETURNING id
                """),
                {
                    "id": paper_id,
                    "external_id": paper_data.get("external_id"),
                    "source": paper_data.get("source"),
                    "title": paper_data.get("title", ""),
                    "abstract": paper_data.get("abstract"),
                    "authors": authors,
                    "publication_date": publication_date,
                    "journal": paper_data.get("journal"),
                    "doi": paper_data.get("doi"),
                    "url": paper_data.get("url"),
                    "pdf_url": paper_data.get("pdf_url"),
                    "citation_count": paper_data.get("citation_count", 0),
                    "reference_count": paper_data.get("reference_count", 0),
                    "fields_of_study": fields_of_study,
                    "metadata": metadata,
                }
            )
            row = result.fetchone()
            actual_id = str(row[0]) if row else str(paper_id)

        logger.debug("Saved paper", paper_id=actual_id)
        return actual_id

    async def get_paper(self, paper_id: str) -> Optional[dict]:
        """获取论文详情"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM papers WHERE id = :id"),
                {"id": paper_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def save_papers_batch(self, papers: list[dict]) -> list[str]:
        """批量保存论文"""
        paper_ids = []
        for paper in papers:
            paper_id = await self.save_paper(paper)
            paper_ids.append(paper_id)

        logger.info("Saved papers batch", count=len(paper_ids))
        return paper_ids

    async def get_papers_by_ids(self, paper_ids: list[str]) -> list[dict]:
        """批量获取论文"""
        if not paper_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM papers WHERE id = ANY(:ids)"),
                {"ids": paper_ids}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def save_embedding(
        self,
        paper_id: str,
        embedding: list[float],
        model_name: str = "bge-m3",
    ) -> str:
        """保存嵌入向量"""
        embedding_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO embeddings (id, paper_id, model_name, vector, dimensions)
                    VALUES (:id, :paper_id, :model_name, :vector, :dimensions)
                    ON CONFLICT (paper_id, model_name)
                    DO UPDATE SET vector = :vector, dimensions = :dimensions
                """),
                {
                    "id": embedding_id,
                    "paper_id": paper_id,
                    "model_name": model_name,
                    "vector": str(embedding),
                    "dimensions": len(embedding),
                }
            )

        return embedding_id

    async def save_cluster(self, cluster_data: dict) -> str:
        """保存聚类结果"""
        cluster_id = cluster_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO clusters (id, project_id, name, description, algorithm,
                                        parameters, quality_score, size)
                    VALUES (:id, :project_id, :name, :description, :algorithm,
                            :parameters, :quality_score, :size)
                """),
                {
                    "id": cluster_id,
                    "project_id": cluster_data.get("project_id"),
                    "name": cluster_data.get("name"),
                    "description": cluster_data.get("description"),
                    "algorithm": cluster_data.get("algorithm", "leiden"),
                    "parameters": cluster_data.get("parameters"),
                    "quality_score": cluster_data.get("quality_score", 0.0),
                    "size": cluster_data.get("size", 0),
                }
            )

        logger.info("Saved cluster", cluster_id=cluster_id)
        return cluster_id

    async def save_kg_entities(self, entities: list[dict]) -> list[str]:
        """保存知识图谱实体"""
        entity_ids = []

        async with self.session() as session:
            for entity in entities:
                entity_id = entity.get("id", str(uuid.uuid4()))

                await session.execute(
                    text("""
                        INSERT INTO kg_entities (id, name, entity_type, normalized_name, paper_ids, metadata)
                        VALUES (:id, :name, :entity_type, :normalized_name, :paper_ids, :metadata)
                    """),
                    {
                        "id": entity_id,
                        "name": entity.get("name"),
                        "entity_type": entity.get("entity_type"),
                        "normalized_name": entity.get("normalized_name"),
                        "paper_ids": entity.get("paper_ids"),
                        "metadata": entity.get("metadata"),
                    }
                )

                entity_ids.append(entity_id)

        logger.info("Saved KG entities", count=len(entity_ids))
        return entity_ids

    async def save_kg_relations(self, relations: list[dict]) -> list[str]:
        """保存知识图谱关系"""
        relation_ids = []

        async with self.session() as session:
            for relation in relations:
                relation_id = relation.get("id", str(uuid.uuid4()))

                await session.execute(
                    text("""
                        INSERT INTO kg_relations (id, source_entity_id, target_entity_id,
                                                relation_type, paper_ids, confidence, metadata)
                        VALUES (:id, :source_entity_id, :target_entity_id,
                                :relation_type, :paper_ids, :confidence, :metadata)
                    """),
                    {
                        "id": relation_id,
                        "source_entity_id": relation.get("source_entity_id"),
                        "target_entity_id": relation.get("target_entity_id"),
                        "relation_type": relation.get("relation_type"),
                        "paper_ids": relation.get("paper_ids"),
                        "confidence": relation.get("confidence", 1.0),
                        "metadata": relation.get("metadata"),
                    }
                )

                relation_ids.append(relation_id)

        logger.info("Saved KG relations", count=len(relation_ids))
        return relation_ids

    async def save_evidence_card(self, card_data: dict) -> str:
        """保存证据卡片"""
        card_id = card_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO evidence_cards (id, paper_id, claim, evidence_span,
                                              method, metric, limitation, confidence, cluster_id)
                    VALUES (:id, :paper_id, :claim, :evidence_span,
                            :method, :metric, :limitation, :confidence, :cluster_id)
                """),
                {
                    "id": card_id,
                    "paper_id": card_data.get("paper_id"),
                    "claim": card_data.get("claim"),
                    "evidence_span": card_data.get("evidence_span"),
                    "method": card_data.get("method"),
                    "metric": card_data.get("metric"),
                    "limitation": card_data.get("limitation"),
                    "confidence": card_data.get("confidence", 0.0),
                    "cluster_id": card_data.get("cluster_id"),
                }
            )

        logger.info("Saved evidence card", card_id=card_id)
        return card_id

    async def save_outline(self, outline_data: dict) -> str:
        """保存大纲"""
        outline_id = outline_data.get("id", str(uuid.uuid4()))

        # 转换 sections 为 JSON 字符串
        sections = outline_data.get("sections")
        if isinstance(sections, list):
            sections = json.dumps(sections)

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO outlines (id, project_id, title, sections, status, version)
                    VALUES (:id, :project_id, :title, CAST(:sections AS jsonb), :status, :version)
                """),
                {
                    "id": outline_id,
                    "project_id": outline_data.get("project_id"),
                    "title": outline_data.get("title"),
                    "sections": sections,
                    "status": outline_data.get("status", "draft"),
                    "version": outline_data.get("version", 1),
                }
            )

        logger.info("Saved outline", outline_id=outline_id)
        return outline_id

    async def save_written_section(self, section_data: dict) -> str:
        """保存或更新已写章节"""
        section_id = section_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO written_content (id, outline_id, section_id, content,
                                               word_count, quality_score, version)
                    VALUES (:id, :outline_id, :section_id, :content,
                            :word_count, :quality_score, :version)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        word_count = EXCLUDED.word_count,
                        quality_score = EXCLUDED.quality_score,
                        version = written_content.version + 1
                """),
                {
                    "id": section_id,
                    "outline_id": section_data.get("outline_id"),
                    "section_id": str(section_data.get("section_id", "")),
                    "content": section_data.get("content"),
                    "word_count": section_data.get("word_count", 0),
                    "quality_score": section_data.get("quality_score", 0.0),
                    "version": section_data.get("version", 1),
                }
            )

        logger.debug("Saved written section", section_id=section_id)
        return section_id

    async def save_artifact(self, artifact_data: dict) -> str:
        """保存产出物"""
        artifact_id = artifact_data.get("id", str(uuid.uuid4()))

        # 产出物通常保存为文件，这里只记录元数据
        logger.info("Saved artifact", artifact_id=artifact_id)
        return artifact_id

    async def get_clusters_by_ids(self, cluster_ids: list[str]) -> list[dict]:
        """批量获取聚类详情（包含 paper_ids）"""
        if not cluster_ids:
            return []

        async with self.session() as session:
            # 获取聚类基本信息
            result = await session.execute(
                text("SELECT * FROM clusters WHERE id = ANY(:ids)"),
                {"ids": cluster_ids}
            )
            rows = result.fetchall()
            clusters = [_convert_uuid_fields(dict(row._mapping)) for row in rows]

            # 获取每个聚类的论文分配
            for cluster in clusters:
                cluster_id = cluster.get("id")
                assignments = await session.execute(
                    text("SELECT paper_id FROM cluster_assignments WHERE cluster_id = :cluster_id"),
                    {"cluster_id": cluster_id}
                )
                paper_rows = assignments.fetchall()
                cluster["paper_ids"] = [str(row[0]) for row in paper_rows]

        return clusters

    async def save_cluster_assignments(self, cluster_id: str, paper_ids: list[str], confidence: float = 1.0):
        """保存聚类分配"""
        async with self.session() as session:
            for paper_id in paper_ids:
                await session.execute(
                    text("""
                        INSERT INTO cluster_assignments (cluster_id, paper_id, confidence)
                        VALUES (:cluster_id, :paper_id, :confidence)
                        ON CONFLICT (cluster_id, paper_id) DO UPDATE SET
                            confidence = EXCLUDED.confidence
                    """),
                    {"cluster_id": cluster_id, "paper_id": paper_id, "confidence": confidence}
                )

        logger.debug("Saved cluster assignments", cluster_id=cluster_id, paper_count=len(paper_ids))

    async def get_kg_entities_by_ids(self, entity_ids: list[str]) -> list[dict]:
        """批量获取知识图谱实体"""
        if not entity_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM kg_entities WHERE id = ANY(:ids)"),
                {"ids": entity_ids}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_kg_relations_by_ids(self, relation_ids: list[str]) -> list[dict]:
        """批量获取知识图谱关系"""
        if not relation_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM kg_relations WHERE id = ANY(:ids)"),
                {"ids": relation_ids}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_evidence_cards_by_ids(self, card_ids: list[str]) -> list[dict]:
        """批量获取证据卡片"""
        if not card_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM evidence_cards WHERE id = ANY(:ids)"),
                {"ids": card_ids}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_written_sections_by_ids(self, section_ids: list[str]) -> list[dict]:
        """批量获取已写章节"""
        if not section_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM written_content WHERE id = ANY(:ids)"),
                {"ids": section_ids}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_outline_by_id(self, outline_id: str) -> Optional[dict]:
        """获取大纲详情"""
        if not outline_id:
            return None

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM outlines WHERE id = :id"),
                {"id": outline_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_project(self, project_id: str) -> Optional[dict]:
        """获取项目详情"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM projects WHERE id = :id"),
                {"id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def save_pipeline_checkpoint(self, checkpoint_data: dict) -> str:
        """保存 Pipeline 检查点"""
        checkpoint_id = checkpoint_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO pipeline_checkpoints (id, project_id, node_name, state_snapshot, status)
                    VALUES (:id, :project_id, :node_name, :state_snapshot, :status)
                    ON CONFLICT (project_id, node_name) DO UPDATE SET
                        state_snapshot = EXCLUDED.state_snapshot,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                """),
                {
                    "id": checkpoint_id,
                    "project_id": checkpoint_data.get("project_id"),
                    "node_name": checkpoint_data.get("node_name"),
                    "state_snapshot": json.dumps(checkpoint_data.get("state_snapshot", {})),
                    "status": checkpoint_data.get("status", "in_progress"),
                }
            )

        logger.debug("Saved pipeline checkpoint", checkpoint_id=checkpoint_id, node=checkpoint_data.get("node_name"))
        return checkpoint_id

    async def get_pipeline_checkpoint(self, project_id: str, node_name: str) -> Optional[dict]:
        """获取 Pipeline 检查点"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id AND node_name = :node_name
                """),
                {"project_id": project_id, "node_name": node_name}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_latest_checkpoint(self, project_id: str) -> Optional[dict]:
        """获取项目最新的检查点"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"project_id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_all_checkpoints(self, project_id: str) -> list[dict]:
        """获取项目所有检查点（按创建时间排序）"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id
                    ORDER BY created_at ASC
                """),
                {"project_id": project_id}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_latest_successful_checkpoint(self, project_id: str) -> Optional[dict]:
        """获取项目最新的成功检查点（含完整 PipelineState）"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"project_id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        cp = _convert_uuid_fields(dict(row._mapping))
        # 解析 state_snapshot JSON
        snapshot = cp.get("state_snapshot")
        if isinstance(snapshot, str):
            try:
                cp["state_snapshot"] = json.loads(snapshot)
            except (json.JSONDecodeError, TypeError):
                pass
        return cp

    async def save_audit_log(self, audit_data: dict) -> str:
        """保存审计日志"""
        audit_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO pipeline_audit_log (id, project_id, node_name, event_type, event_data, duration_ms)
                    VALUES (:id, :project_id, :node_name, :event_type, :event_data, :duration_ms)
                """),
                {
                    "id": audit_id,
                    "project_id": audit_data.get("project_id"),
                    "node_name": audit_data.get("node_name"),
                    "event_type": audit_data.get("event_type"),
                    "event_data": json.dumps(audit_data.get("event_data", {})),
                    "duration_ms": audit_data.get("duration_ms"),
                }
            )

        return audit_id

    async def get_audit_logs(self, project_id: str, node_name: str | None = None) -> list[dict]:
        """获取审计日志"""
        async with self.session() as session:
            if node_name:
                result = await session.execute(
                    text("""
                        SELECT * FROM pipeline_audit_log
                        WHERE project_id = :project_id AND node_name = :node_name
                        ORDER BY created_at DESC
                    """),
                    {"project_id": project_id, "node_name": node_name}
                )
            else:
                result = await session.execute(
                    text("""
                        SELECT * FROM pipeline_audit_log
                        WHERE project_id = :project_id
                        ORDER BY created_at DESC
                    """),
                    {"project_id": project_id}
                )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def save_project(self, project_data: dict) -> str:
        """保存项目"""
        import json
        project_id = project_data.get("id", str(uuid.uuid4()))
        user_id = project_data.get("user_id")
        config = project_data.get("config")
        if config and isinstance(config, dict):
            config = json.dumps(config)

        async with self.session() as session:
            if user_id:
                await session.execute(
                    text("""
                        INSERT INTO projects (id, user_id, name, description, query, status, config)
                        VALUES (:id, :user_id, :name, :description, :query, :status, :config)
                    """),
                    {
                        "id": project_id,
                        "user_id": user_id,
                        "name": project_data.get("name"),
                        "description": project_data.get("description"),
                        "query": project_data.get("query"),
                        "status": project_data.get("status", "created"),
                        "config": config,
                    }
                )
            else:
                await session.execute(
                    text("""
                        INSERT INTO projects (id, name, description, query, status, config)
                        VALUES (:id, :name, :description, :query, :status, :config)
                    """),
                    {
                        "id": project_id,
                        "name": project_data.get("name"),
                        "description": project_data.get("description"),
                        "query": project_data.get("query"),
                        "status": project_data.get("status", "created"),
                        "config": config,
                    }
                )

        logger.info("Saved project", project_id=project_id)
        return project_id

    # =========================================================================
    # 用户相关方法
    # =========================================================================

    async def save_user(self, user_data: dict) -> str:
        """保存用户，返回用户 ID"""
        user_id = user_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO users (id, email, hashed_password, full_name, role, is_active)
                    VALUES (:id, :email, :hashed_password, :full_name, :role, :is_active)
                    RETURNING id
                """),
                {
                    "id": user_id,
                    "email": user_data["email"],
                    "hashed_password": user_data["hashed_password"],
                    "full_name": user_data.get("full_name"),
                    "role": user_data.get("role", "user"),
                    "is_active": user_data.get("is_active", True),
                }
            )
            row = result.fetchone()
            actual_id = str(row[0]) if row else str(user_id)

        logger.info("Saved user", user_id=actual_id)
        return actual_id

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """根据 ID 获取用户"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM users WHERE id = :id"),
                {"id": user_id}
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """根据邮箱获取用户"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM users WHERE email = :email"),
                {"email": email}
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def update_user(self, user_id: str, update_data: dict) -> None:
        """更新用户信息"""
        if not update_data:
            return

        set_clauses = []
        params = {"id": user_id}
        for key, value in update_data.items():
            set_clauses.append(f"{key} = :{key}")
            params[key] = value

        async with self.session() as session:
            await session.execute(
                text(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :id"),
                params
            )

        logger.info("Updated user", user_id=user_id)

    async def list_users(self, skip: int = 0, limit: int = 20) -> tuple[list[dict], int]:
        """列出所有用户"""
        async with self.session() as session:
            count_result = await session.execute(
                text("SELECT COUNT(*) FROM users")
            )
            total = count_result.scalar()

            result = await session.execute(
                text("SELECT * FROM users ORDER BY created_at DESC LIMIT :limit OFFSET :skip"),
                {"limit": limit, "skip": skip}
            )
            rows = result.fetchall()

        users = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return users, total

    async def set_user_active(self, user_id: str, is_active: bool) -> None:
        """设置用户激活状态"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE users SET is_active = :is_active WHERE id = :id"),
                {"id": user_id, "is_active": is_active}
            )

    async def set_user_role(self, user_id: str, role: str) -> None:
        """设置用户角色"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE users SET role = :role WHERE id = :id"),
                {"id": user_id, "role": role}
            )

    # =========================================================================
    # Refresh Token 相关方法
    # =========================================================================

    async def save_refresh_token(self, token_hash: str, user_id: str, expires_at: datetime) -> str:
        """保存 Refresh Token"""
        token_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO refresh_tokens (id, token_hash, user_id, expires_at)
                    VALUES (:id, :token_hash, :user_id, :expires_at)
                """),
                {
                    "id": token_id,
                    "token_hash": token_hash,
                    "user_id": user_id,
                    "expires_at": expires_at,
                }
            )

        return token_id

    async def get_refresh_token(self, token_hash: str) -> Optional[dict]:
        """获取有效的 Refresh Token"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM refresh_tokens
                    WHERE token_hash = :token_hash
                      AND is_revoked = FALSE
                      AND expires_at > NOW()
                """),
                {"token_hash": token_hash}
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def revoke_refresh_token(self, token_hash: str) -> None:
        """撤销 Refresh Token"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE refresh_tokens SET is_revoked = TRUE WHERE token_hash = :token_hash"),
                {"token_hash": token_hash}
            )

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """撤销用户的所有 Refresh Token"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE refresh_tokens SET is_revoked = TRUE WHERE user_id = :user_id"),
                {"user_id": user_id}
            )

    # =========================================================================
    # 用户活动日志相关方法
    # =========================================================================

    async def log_activity(
        self,
        user_id: str,
        action: str,
        resource_type: str = None,
        resource_id: str = None,
        details: dict = None,
        ip_address: str = None,
    ) -> str:
        """记录用户活动"""
        activity_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO user_activities (id, user_id, action, resource_type, resource_id, details, ip_address)
                    VALUES (:id, :user_id, :action, :resource_type, :resource_id, :details, :ip_address)
                """),
                {
                    "id": activity_id,
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": json.dumps(details) if details else None,
                    "ip_address": ip_address,
                }
            )

        return activity_id

    async def get_user_activities(self, user_id: str, skip: int = 0, limit: int = 20) -> list[dict]:
        """获取用户活动记录"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM user_activities
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"user_id": user_id, "limit": limit, "skip": skip}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    # =========================================================================
    # 项目查询扩展
    # =========================================================================

    async def list_projects_by_user(self, user_id: str, skip: int = 0, limit: int = 20) -> tuple[list[dict], int]:
        """列出用户的项目"""
        async with self.session() as session:
            count_result = await session.execute(
                text("SELECT COUNT(*) FROM projects WHERE user_id = :user_id"),
                {"user_id": user_id}
            )
            total = count_result.scalar()

            result = await session.execute(
                text("""
                    SELECT * FROM projects
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"user_id": user_id, "limit": limit, "skip": skip}
            )
            rows = result.fetchall()

        projects = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return projects, total

    async def list_all_projects(self, skip: int = 0, limit: int = 20) -> tuple[list[dict], int]:
        """列出所有项目（管理员用）"""
        async with self.session() as session:
            count_result = await session.execute(
                text("SELECT COUNT(*) FROM projects")
            )
            total = count_result.scalar()

            result = await session.execute(
                text("""
                    SELECT * FROM projects
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"limit": limit, "skip": skip}
            )
            rows = result.fetchall()

        projects = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return projects, total

    async def get_system_stats(self) -> dict:
        """获取系统统计信息"""
        async with self.session() as session:
            users_result = await session.execute(text("SELECT COUNT(*) FROM users"))
            total_users = users_result.scalar()

            active_result = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            )
            active_users = active_result.scalar()

            projects_result = await session.execute(text("SELECT COUNT(*) FROM projects"))
            total_projects = projects_result.scalar()

            papers_result = await session.execute(text("SELECT COUNT(*) FROM papers"))
            total_papers = papers_result.scalar()

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_projects": total_projects,
            "total_papers": total_papers,
        }

    async def update_project_status(self, project_id: str, status: str):
        """更新项目状态"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE projects SET status = :status, updated_at = NOW() WHERE id = :id"),
                {"id": project_id, "status": status}
            )

        logger.info("Updated project status", project_id=project_id, status=status)

    async def get_outline_by_project_id(self, project_id: str) -> Optional[dict]:
        """根据项目 ID 获取大纲"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM outlines WHERE project_id = :project_id ORDER BY version DESC LIMIT 1"),
                {"project_id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def save_visualization(self, project_id: str, visualization_data: dict) -> str:
        """保存可视化数据到 pipeline_checkpoints"""
        viz_id = str(uuid.uuid4())
        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO pipeline_checkpoints (id, project_id, node_name, state_snapshot, status)
                    VALUES (:id, :project_id, :node_name, :state_snapshot, :status)
                    ON CONFLICT (project_id, node_name) DO UPDATE SET
                        state_snapshot = EXCLUDED.state_snapshot,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                """),
                {
                    "id": viz_id,
                    "project_id": project_id,
                    "node_name": "visualization_data",
                    "state_snapshot": json.dumps(visualization_data),
                    "status": "completed",
                }
            )
        logger.info("Saved visualization data", project_id=project_id)
        return viz_id

    async def get_visualization_by_project_id(self, project_id: str) -> Optional[dict]:
        """根据项目 ID 获取可视化数据"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT state_snapshot FROM pipeline_checkpoints
                    WHERE project_id = :project_id AND node_name = 'visualization_data'
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"project_id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        snapshot = row[0]
        if isinstance(snapshot, str):
            import json as _json
            return _json.loads(snapshot)
        return snapshot

    async def get_written_sections_by_project_id(self, project_id: str) -> list[dict]:
        """根据项目 ID 获取已写章节"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT wc.* FROM written_content wc
                    JOIN outlines o ON wc.outline_id = o.id
                    WHERE o.project_id = :project_id
                    ORDER BY wc.created_at
                """),
                {"project_id": project_id}
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]


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
