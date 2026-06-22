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
        elif key.endswith("_ids") and value is None:
            result[key] = []
        elif key.endswith("_ids") and isinstance(value, (list, tuple, set)):
            result[key] = [
                str(v) if isinstance(v, uuid.UUID) or hasattr(v, '__class__') and 'UUID' in v.__class__.__name__ else v
                for v in value
            ]
        else:
            result[key] = value
    return result

from ..config import get_settings

logger = structlog.get_logger()


def _json_dumps(value: Any, default: Any = None) -> str:
    """Serialize values for explicit JSONB casts used by asyncpg."""
    if value is None:
        value = default
    return json.dumps(value, ensure_ascii=False)


def _stringify_scalar(value: Any) -> str:
    """Normalize structured evidence-card fields to a DB-safe string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return _json_dumps(list(value), [])
    if isinstance(value, dict):
        return _json_dumps(value, {})
    return str(value)


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
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_timeout=30,
            connect_args={
                "server_settings": {"statement_timeout": "30000"},  # 30s 语句超时
            },
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

        papers = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        order = {str(pid): idx for idx, pid in enumerate(paper_ids)}
        papers.sort(key=lambda paper: order.get(str(paper.get("id")), len(order)))
        return papers

    async def save_embedding(
        self,
        paper_id: str,
        embedding: list[float],
        model_name: str = "bge-m3",
    ) -> str:
        """保存嵌入向量"""
        embedding_id = str(uuid.uuid4())

        async with self.session() as session:
            result = await session.execute(
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
            result = await session.execute(
                text("""
                    INSERT INTO clusters (id, project_id, name, description, algorithm,
                                        parameters, quality_score, size)
                    VALUES (:id, :project_id, :name, :description, :algorithm,
                            CAST(:parameters AS jsonb), :quality_score, :size)
                """),
                {
                    "id": cluster_id,
                    "project_id": cluster_data.get("project_id"),
                    "name": cluster_data.get("name"),
                    "description": cluster_data.get("description"),
                    "algorithm": cluster_data.get("algorithm", "leiden"),
                    "parameters": _json_dumps(cluster_data.get("parameters"), {}),
                    "quality_score": cluster_data.get("quality_score", 0.0),
                    "size": cluster_data.get("size", 0),
                }
            )

        logger.info("Saved cluster", cluster_id=cluster_id)
        return cluster_id

    async def save_kg_entities(self, entities: list[dict]) -> list[str]:
        """保存知识图谱实体（ON CONFLICT 合并 paper_ids，支持并发写入）"""
        entity_ids = []

        async with self.session() as session:
            for entity in entities:
                entity_id = entity.get("id", str(uuid.uuid4()))

                result = await session.execute(
                    text("""
                        INSERT INTO kg_entities (id, name, entity_type, normalized_name, paper_ids, metadata)
                        VALUES (:id, :name, :entity_type, :normalized_name, :paper_ids, CAST(:metadata AS jsonb))
                        ON CONFLICT (normalized_name) DO UPDATE
                        SET paper_ids = (
                            SELECT array_agg(DISTINCT x) FROM unnest(kg_entities.paper_ids || EXCLUDED.paper_ids) AS x
                        )
                        RETURNING id
                    """),
                    {
                        "id": entity_id,
                        "name": entity.get("name"),
                        "entity_type": entity.get("entity_type"),
                        "normalized_name": entity.get("normalized_name"),
                        "paper_ids": entity.get("paper_ids"),
                        "metadata": _json_dumps(entity.get("metadata"), {}),
                    }
                )
                row = result.fetchone()
                entity_ids.append(str(row[0]) if row else entity_id)

            await session.commit()

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
                                :relation_type, :paper_ids, :confidence, CAST(:metadata AS jsonb))
                    """),
                    {
                        "id": relation_id,
                        "source_entity_id": relation.get("source_entity_id"),
                        "target_entity_id": relation.get("target_entity_id"),
                        "relation_type": relation.get("relation_type"),
                        "paper_ids": relation.get("paper_ids"),
                        "confidence": relation.get("confidence", 1.0),
                        "metadata": _json_dumps(relation.get("metadata"), {}),
                    }
                )

                relation_ids.append(relation_id)

            await session.commit()

        logger.info("Saved KG relations", count=len(relation_ids))
        return relation_ids

    async def save_evidence_card(self, card_data: dict) -> str:
        """保存证据卡片"""
        card_id = card_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO evidence_cards (id, project_id, paper_id, claim, evidence_span,
                                              method, metric, limitation, confidence, cluster_id)
                    VALUES (:id, :project_id, :paper_id, :claim, :evidence_span,
                            :method, :metric, :limitation, :confidence, :cluster_id)
                    ON CONFLICT (project_id, paper_id) WHERE project_id IS NOT NULL DO UPDATE SET
                        claim = EXCLUDED.claim,
                        evidence_span = EXCLUDED.evidence_span,
                        method = EXCLUDED.method,
                        metric = EXCLUDED.metric,
                        limitation = EXCLUDED.limitation,
                        confidence = EXCLUDED.confidence,
                        cluster_id = EXCLUDED.cluster_id
                    RETURNING id
                """),
                {
                    "id": card_id,
                    "project_id": card_data.get("project_id"),
                    "paper_id": card_data.get("paper_id"),
                    "claim": card_data.get("claim") or "Claim not specified",
                    "evidence_span": card_data.get("evidence_span") or card_data.get("source_span") or "",
                    "method": card_data.get("method") or "Method not specified",
                    "metric": _stringify_scalar(card_data.get("metric") or card_data.get("result") or ""),
                    "limitation": card_data.get("limitation") or "Limitation not specified",
                    "confidence": card_data.get("confidence", 0.0),
                    "cluster_id": card_data.get("cluster_id"),
                }
            )
            row = result.fetchone()

        actual_id = str(row[0]) if row else card_id
        logger.info("Saved evidence card", card_id=actual_id)
        return actual_id

    async def save_community_memory(self, memory_data: dict) -> str:
        """Persist a synthesized community memory, upserting by project and cluster."""
        memory_id = memory_data.get("id", str(uuid.uuid4()))

        async with self.session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO community_memories (
                        id, project_id, cluster_id, summary, method_families, key_claims,
                        limitations, future_directions, foundation_papers, development_papers,
                        frontier_papers, representative_papers, cross_community_links,
                        proof_ids, metadata
                    )
                    VALUES (
                        :id, :project_id, :cluster_id, :summary,
                        CAST(:method_families AS jsonb), CAST(:key_claims AS jsonb),
                        CAST(:limitations AS jsonb), CAST(:future_directions AS jsonb),
                        CAST(:foundation_papers AS jsonb), CAST(:development_papers AS jsonb),
                        CAST(:frontier_papers AS jsonb), CAST(:representative_papers AS jsonb),
                        CAST(:cross_community_links AS jsonb), CAST(:proof_ids AS jsonb),
                        CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (project_id, cluster_id) DO UPDATE SET
                        summary = EXCLUDED.summary,
                        method_families = EXCLUDED.method_families,
                        key_claims = EXCLUDED.key_claims,
                        limitations = EXCLUDED.limitations,
                        future_directions = EXCLUDED.future_directions,
                        foundation_papers = EXCLUDED.foundation_papers,
                        development_papers = EXCLUDED.development_papers,
                        frontier_papers = EXCLUDED.frontier_papers,
                        representative_papers = EXCLUDED.representative_papers,
                        cross_community_links = EXCLUDED.cross_community_links,
                        proof_ids = EXCLUDED.proof_ids,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    RETURNING id
                """),
                {
                    "id": memory_id,
                    "project_id": memory_data.get("project_id"),
                    "cluster_id": memory_data.get("cluster_id"),
                    "summary": memory_data.get("summary", ""),
                    "method_families": _json_dumps(memory_data.get("method_families"), []),
                    "key_claims": _json_dumps(memory_data.get("key_claims"), []),
                    "limitations": _json_dumps(memory_data.get("limitations"), []),
                    "future_directions": _json_dumps(memory_data.get("future_directions"), []),
                    "foundation_papers": _json_dumps(memory_data.get("foundation_papers"), []),
                    "development_papers": _json_dumps(memory_data.get("development_papers"), []),
                    "frontier_papers": _json_dumps(memory_data.get("frontier_papers"), []),
                    "representative_papers": _json_dumps(memory_data.get("representative_papers"), []),
                    "cross_community_links": _json_dumps(memory_data.get("cross_community_links"), []),
                    "proof_ids": _json_dumps(memory_data.get("proof_ids"), []),
                    "metadata": _json_dumps(memory_data.get("metadata"), {}),
                },
            )
            row = result.fetchone()

        actual_id = str(row[0]) if row else memory_id
        logger.info("Saved community memory", memory_id=actual_id)
        return actual_id

    async def get_community_memories_by_ids(self, memory_ids: list[str]) -> list[dict]:
        """Fetch community memories by ids."""
        if not memory_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM community_memories WHERE id = ANY(:ids)"),
                {"ids": memory_ids},
            )
            rows = result.fetchall()

        memories = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        order = {str(mid): idx for idx, mid in enumerate(memory_ids)}
        memories.sort(key=lambda memory: order.get(str(memory.get("id")), len(order)))
        return memories

    async def get_community_memories_by_project(self, project_id: str) -> list[dict]:
        """Fetch all community memories for a project."""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM community_memories WHERE project_id = :project_id ORDER BY created_at"),
                {"project_id": project_id},
            )
            rows = result.fetchall()
        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

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
        # Use deterministic ID based on outline_id + section name to prevent duplicates
        if not section_data.get("id"):
            oid = section_data.get("outline_id", "")
            sname = str(section_data.get("section_id", ""))
            section_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{oid}:{sname}"))
        else:
            section_id = section_data["id"]

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
        if isinstance(config, dict):
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

        # 安全修复: 白名单验证列名，防止 SQL 注入
        _ALLOWED_USER_COLUMNS = {
            "email", "hashed_password", "full_name", "role",
            "is_active", "last_login_at",
        }

        set_clauses = []
        params = {"id": user_id}
        for key, value in update_data.items():
            if key not in _ALLOWED_USER_COLUMNS:
                raise ValueError(f"不允许更新的字段: {key}")
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

            # Pipeline runs 统计
            runs_result = await session.execute(text("SELECT COUNT(*) FROM pipeline_runs"))
            total_runs = runs_result.scalar() or 0

            running_result = await session.execute(
                text("SELECT COUNT(*) FROM projects WHERE status = 'running'")
            )
            running_projects = running_result.scalar() or 0

            # LLM 调用统计
            llm_result = await session.execute(text("SELECT COUNT(*) FROM llm_calls"))
            total_llm_calls = llm_result.scalar() or 0

            cost_result = await session.execute(
                text("SELECT COALESCE(SUM(cost), 0) FROM llm_calls")
            )
            total_cost = float(cost_result.scalar() or 0)

            tokens_result = await session.execute(
                text("SELECT COALESCE(SUM(total_tokens), 0) FROM llm_calls")
            )
            total_tokens = int(tokens_result.scalar() or 0)

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_projects": total_projects,
            "running_projects": running_projects,
            "total_papers": total_papers,
            "total_runs": total_runs,
            "total_llm_calls": total_llm_calls,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
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

    # =========================================================================
    # 可观测性：Pipeline Runs / Node Executions / LLM Calls
    # =========================================================================

    async def create_pipeline_run(
        self,
        project_id: str,
        topic: str | None = None,
        config: dict | None = None,
        created_by: str | None = None,
    ) -> str:
        """创建 Pipeline 运行记录，返回 run_id"""
        run_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO pipeline_runs (id, project_id, topic, config, created_by)
                    VALUES (:id, :project_id, :topic, :config, :created_by)
                """),
                {
                    "id": run_id,
                    "project_id": project_id,
                    "topic": topic,
                    "config": json.dumps(config) if config else None,
                    "created_by": created_by,
                }
            )

        logger.info("Created pipeline run", run_id=run_id, project_id=project_id)
        return run_id

    async def finish_pipeline_run(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        elapsed_seconds: float | None = None,
        total_tokens: int = 0,
        total_cost: float = 0,
        llm_calls_count: int = 0,
    ) -> None:
        """结束 Pipeline 运行"""
        async with self.session() as session:
            await session.execute(
                text("""
                    UPDATE pipeline_runs
                    SET status = :status,
                        error_message = :error_message,
                        finished_at = NOW(),
                        elapsed_seconds = COALESCE(:elapsed_seconds, EXTRACT(EPOCH FROM (NOW() - created_at))),
                        total_tokens = :total_tokens,
                        total_cost = :total_cost,
                        total_llm_calls = :llm_calls_count
                    WHERE id = :id
                """),
                {
                    "id": run_id,
                    "status": status,
                    "error_message": error_message,
                    "elapsed_seconds": elapsed_seconds,
                    "total_tokens": total_tokens,
                    "total_cost": total_cost,
                    "llm_calls_count": llm_calls_count,
                }
            )

        logger.info("Finished pipeline run", run_id=run_id, status=status)

    async def update_pipeline_run_stats(
        self,
        run_id: str,
        total_tokens: int = 0,
        total_cost: float = 0,
        llm_calls_count: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_nodes: int | None = None,
        completed_nodes: int | None = None,
        failed_nodes: int | None = None,
    ) -> None:
        """更新 Pipeline 运行的汇总统计"""
        set_parts = [
            "total_prompt_tokens = :prompt_tokens",
            "total_completion_tokens = :completion_tokens",
            "total_tokens = :total_tokens",
            "total_cost = :total_cost",
            "total_llm_calls = :llm_calls_count",
        ]
        params: dict[str, Any] = {
            "id": run_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "llm_calls_count": llm_calls_count,
        }

        if total_nodes is not None:
            set_parts.append("total_nodes = :total_nodes")
            params["total_nodes"] = total_nodes
        if completed_nodes is not None:
            set_parts.append("completed_nodes = :completed_nodes")
            params["completed_nodes"] = completed_nodes
        if failed_nodes is not None:
            set_parts.append("failed_nodes = :failed_nodes")
            params["failed_nodes"] = failed_nodes

        async with self.session() as session:
            await session.execute(
                text(f"UPDATE pipeline_runs SET {', '.join(set_parts)} WHERE id = :id"),
                params,
            )

    async def refresh_pipeline_run_usage_from_calls(self, run_id: str) -> None:
        """Recompute run usage from persisted call rows.

        Request-level audit rows are the source of truth while the pipeline is
        running. Keeping the run summary in sync makes usage pages useful before
        the final tracker summary is written.
        """
        async with self.session() as session:
            await session.execute(
                text("""
                    UPDATE pipeline_runs pr
                    SET total_prompt_tokens = COALESCE(stats.prompt_tokens, 0),
                        total_completion_tokens = COALESCE(stats.completion_tokens, 0),
                        total_tokens = COALESCE(stats.total_tokens, 0),
                        total_cost = COALESCE(stats.total_cost, 0),
                        total_llm_calls = COALESCE(stats.call_count, 0)
                    FROM (
                        SELECT
                            pipeline_run_id,
                            COUNT(*) AS call_count,
                            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                            COALESCE(SUM(total_tokens), 0) AS total_tokens,
                            COALESCE(SUM(cost), 0) AS total_cost
                        FROM llm_calls
                        WHERE pipeline_run_id = :run_id
                        GROUP BY pipeline_run_id
                    ) stats
                    WHERE pr.id = stats.pipeline_run_id
                      AND pr.id = :run_id
                """),
                {"run_id": run_id},
            )

    async def create_node_execution(
        self,
        pipeline_run_id: str,
        node_name: str,
        node_type: str,
        index: int | None = None,
    ) -> str:
        """创建节点执行记录，返回 execution_id"""
        execution_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO node_executions (id, pipeline_run_id, node_name, node_type, index, started_at)
                    VALUES (:id, :pipeline_run_id, :node_name, :node_type, :index, NOW())
                """),
                {
                    "id": execution_id,
                    "pipeline_run_id": pipeline_run_id,
                    "node_name": node_name,
                    "node_type": node_type,
                    "index": index,
                }
            )

        logger.debug("Created node execution", execution_id=execution_id, node=node_name)
        return execution_id

    async def finish_node_execution(
        self,
        execution_id: str,
        status: str,
        error_message: str | None = None,
        error_traceback: str | None = None,
        input_summary: dict | None = None,
        output_summary: dict | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost: float = 0,
        llm_calls_count: int = 0,
        retry_count: int = 0,
        metadata: dict | None = None,
    ) -> None:
        """结束节点执行"""
        async with self.session() as session:
            await session.execute(
                text("""
                    UPDATE node_executions
                    SET status = :status,
                        error_message = :error_message,
                        error_traceback = :error_traceback,
                        input_summary = :input_summary,
                        output_summary = :output_summary,
                        prompt_tokens = :prompt_tokens,
                        completion_tokens = :completion_tokens,
                        total_tokens = :total_tokens,
                        cost = :cost,
                        llm_calls_count = :llm_calls_count,
                        retry_count = :retry_count,
                        finished_at = NOW(),
                        elapsed_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
                        metadata = :metadata
                    WHERE id = :id
                """),
                {
                    "id": execution_id,
                    "status": status,
                    "error_message": error_message,
                    "error_traceback": error_traceback,
                    "input_summary": json.dumps(input_summary) if input_summary else None,
                    "output_summary": json.dumps(output_summary) if output_summary else None,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost": cost,
                    "llm_calls_count": llm_calls_count,
                    "retry_count": retry_count,
                    "metadata": json.dumps(metadata) if metadata else None,
                }
            )

        logger.debug("Finished node execution", execution_id=execution_id, status=status)

    async def create_llm_call(
        self,
        pipeline_run_id: str,
        node_execution_id: str | None,
        call_type: str,
        provider_name: str,
        model_name: str,
        project_id: str | None = None,
        node_name: str | None = None,
        requested_model: str | None = None,
        upstream_model: str | None = None,
        api_base_url: str | None = None,
        api_key_hint: str | None = None,
        is_stream: bool = False,
        latency_ms: int = 0,
        first_token_ms: int | None = None,
        input_preview: str | None = None,
        output_preview: str | None = None,
        request_metadata: dict | None = None,
        retry_of: str | None = None,
        input_price_per_m: float | None = None,
        output_price_per_m: float | None = None,
        status: str = "running",
    ) -> str:
        """创建 LLM 调用记录（先插入骨架，完成时更新统计）"""
        call_id = str(uuid.uuid4())

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO llm_calls (
                        id, project_id, pipeline_run_id, node_execution_id, node_name,
                        call_type, provider_name, model_name, requested_model, upstream_model,
                        api_base_url, api_key_hint, status,
                        is_stream, latency_ms, first_token_ms,
                        input_preview, output_preview, request_metadata, retry_of,
                        input_price_per_m, output_price_per_m
                    ) VALUES (
                        :id, :project_id, :pipeline_run_id, :node_execution_id, :node_name,
                        :call_type, :provider_name, :model_name, :requested_model, :upstream_model,
                        :api_base_url, :api_key_hint, :status,
                        :is_stream, :latency_ms, :first_token_ms,
                        :input_preview, :output_preview, :request_metadata, :retry_of,
                        :input_price_per_m, :output_price_per_m
                    )
                """),
                {
                    "id": call_id,
                    "project_id": project_id,
                    "pipeline_run_id": pipeline_run_id,
                    "node_execution_id": node_execution_id,
                    "node_name": node_name,
                    "call_type": call_type,
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "requested_model": requested_model or model_name,
                    "upstream_model": upstream_model or model_name,
                    "api_base_url": api_base_url,
                    "api_key_hint": api_key_hint,
                    "status": status,
                    "is_stream": is_stream,
                    "latency_ms": latency_ms,
                    "first_token_ms": first_token_ms,
                    "input_preview": input_preview,
                    "output_preview": output_preview,
                    "request_metadata": json.dumps(request_metadata) if request_metadata else None,
                    "retry_of": retry_of,
                    "input_price_per_m": input_price_per_m,
                    "output_price_per_m": output_price_per_m,
                }
            )

        return call_id

    async def finish_llm_call(
        self,
        call_id: str,
        status: str = "success",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float = 0,
        error_message: str | None = None,
        http_status_code: int | None = None,
        latency_ms: int | None = None,
        output_preview: str | None = None,
        model_name: str | None = None,
        upstream_model: str | None = None,
        input_price_per_m: float | None = None,
        output_price_per_m: float | None = None,
    ) -> None:
        """完成 LLM 调用，更新 token 统计和状态"""
        async with self.session() as session:
            await session.execute(
                text("""
                    UPDATE llm_calls
                    SET status = :status,
                        prompt_tokens = :prompt_tokens,
                        completion_tokens = :completion_tokens,
                        total_tokens = CAST(:prompt_tokens AS INTEGER) + CAST(:completion_tokens AS INTEGER),
                        cost = :cost,
                        error_message = :error_message,
                        http_status_code = :http_status_code,
                        latency_ms = COALESCE(:latency_ms, latency_ms),
                        output_preview = COALESCE(:output_preview, output_preview),
                        model_name = COALESCE(:model_name, model_name),
                        upstream_model = COALESCE(:upstream_model, upstream_model),
                        input_price_per_m = COALESCE(:input_price_per_m, input_price_per_m),
                        output_price_per_m = COALESCE(:output_price_per_m, output_price_per_m)
                    WHERE id = :id
                """),
                {
                    "id": call_id,
                    "status": status,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost": cost,
                    "error_message": error_message,
                    "http_status_code": http_status_code,
                    "latency_ms": latency_ms,
                    "output_preview": output_preview,
                    "model_name": model_name,
                    "upstream_model": upstream_model,
                    "input_price_per_m": input_price_per_m,
                    "output_price_per_m": output_price_per_m,
                }
            )

        async with self.session() as session:
            result = await session.execute(
                text("SELECT pipeline_run_id FROM llm_calls WHERE id = :id"),
                {"id": call_id},
            )
            row = result.fetchone()

        if row and row[0]:
            try:
                await self.refresh_pipeline_run_usage_from_calls(str(row[0]))
            except Exception as e:
                logger.warning(
                    "Failed to refresh pipeline run usage from llm_calls",
                    run_id=str(row[0]),
                    error=str(e),
                )

    async def get_pipeline_run_stats(self, run_id: str) -> dict | None:
        """获取 Pipeline 运行的汇总统计"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM pipeline_runs WHERE id = :id"),
                {"id": run_id},
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_node_executions(self, run_id: str) -> list[dict]:
        """获取 Pipeline 运行的所有节点执行记录"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM node_executions
                    WHERE pipeline_run_id = :run_id
                    ORDER BY COALESCE(index, 0), started_at
                """),
                {"run_id": run_id},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_llm_calls(
        self,
        run_id: str,
        node_name: str | None = None,
    ) -> list[dict]:
        """获取 LLM 调用记录，可按 node_name 过滤"""
        async with self.session() as session:
            if node_name:
                result = await session.execute(
                    text("""
                        SELECT lc.* FROM llm_calls lc
                        LEFT JOIN node_executions ne ON lc.node_execution_id = ne.id
                        WHERE lc.pipeline_run_id = :run_id
                          AND COALESCE(lc.node_name, ne.node_name) = :node_name
                        ORDER BY lc.created_at
                    """),
                    {"run_id": run_id, "node_name": node_name},
                )
            else:
                result = await session.execute(
                    text("""
                        SELECT * FROM llm_calls
                        WHERE pipeline_run_id = :run_id
                        ORDER BY created_at
                    """),
                    {"run_id": run_id},
                )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_provider_usage_summary(
        self,
        run_id: str | None = None,
        project_id: str | None = None,
        days: int = 30,
    ) -> list[dict]:
        """按 provider/model 汇总用量（用于成本分析）"""
        # 安全修复: 分离 SQL 模板和参数化条件，避免 f-string SQL 构建
        conditions = ["lc.created_at >= NOW() - INTERVAL '1 day' * :days"]
        params: dict[str, Any] = {"days": days}

        if run_id:
            conditions.append("lc.pipeline_run_id = :run_id")
            params["run_id"] = run_id
        if project_id:
            conditions.append("COALESCE(lc.project_id, pr.project_id) = :project_id")
            params["project_id"] = project_id

        where_clause = " AND ".join(conditions)

        # 构建 JOIN 子句 - 来源固定，不来自用户输入
        join_clause = ""
        if project_id:
            join_clause = "LEFT JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id"

        query = f"""
            SELECT
                lc.provider_name,
                lc.model_name,
                lc.call_type,
                COUNT(*) AS call_count,
                SUM(CASE WHEN lc.status = 'success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN lc.status = 'error' THEN 1 ELSE 0 END) AS error_count,
                SUM(lc.prompt_tokens) AS total_prompt_tokens,
                SUM(lc.completion_tokens) AS total_completion_tokens,
                SUM(lc.total_tokens) AS total_tokens,
                SUM(lc.cost) AS total_cost,
                AVG(lc.latency_ms) AS avg_latency_ms,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lc.latency_ms) AS p50_latency_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY lc.latency_ms) AS p95_latency_ms
            FROM llm_calls lc
            {join_clause}
            WHERE {where_clause}
            GROUP BY lc.provider_name, lc.model_name, lc.call_type
            ORDER BY total_cost DESC
        """

        async with self.session() as session:
            result = await session.execute(
                text(query),
                params,
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
