"""
数据库服务

提供 PostgreSQL 异步数据库访问，使用 pgvector 进行向量存储。
"""

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _convert_uuid_fields(row: dict[str, Any]) -> dict[str, Any]:
    """将 UUID 字段转换为字符串"""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, uuid.UUID) or (
            hasattr(value, "__class__") and "UUID" in value.__class__.__name__
        ):
            result[key] = str(value)
        elif key.endswith("_ids") and value is None:
            result[key] = []
        elif key.endswith("_ids") and isinstance(value, (list, tuple, set)):
            result[key] = [
                str(v)
                if isinstance(v, uuid.UUID)
                or (hasattr(v, "__class__") and "UUID" in v.__class__.__name__)
                else v
                for v in value
            ]
        else:
            result[key] = value
    return result


from ..config import get_settings  # noqa: E402

logger = structlog.get_logger()


def build_database_url(settings: Any) -> URL:
    """Build an asyncpg URL without treating password delimiters as syntax."""

    return URL.create(
        drivername="postgresql+asyncpg",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


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

    def __init__(self, database_url: str | None = None):
        settings = get_settings()
        engine_url: str | URL = (
            build_database_url(settings) if database_url is None else database_url
        )

        self.engine = create_async_engine(
            engine_url,
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

    async def close(self) -> None:
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

    async def save_paper(self, paper_data: dict[str, Any]) -> str:
        """保存论文到数据库，返回数据库中实际的 paper_id"""
        paper_id = str(paper_data.get("id") or uuid.uuid4())

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
                publication_date = (
                    datetime(int(publication_date), 1, 1).date()
                    if len(publication_date) == 4 and publication_date.isdigit()
                    else datetime.fromisoformat(
                        publication_date.replace("Z", "+00:00")
                    ).date()
                )
            except ValueError:
                publication_date = None
        if publication_date is None:
            try:
                year = int(paper_data.get("year") or 0)
                if 1000 <= year <= 9999:
                    publication_date = datetime(year, 1, 1).date()
            except (TypeError, ValueError):
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
                        source = COALESCE(EXCLUDED.source, papers.source),
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), papers.title),
                        abstract = COALESCE(EXCLUDED.abstract, papers.abstract),
                        authors = COALESCE(EXCLUDED.authors, papers.authors),
                        publication_date = COALESCE(
                            EXCLUDED.publication_date, papers.publication_date
                        ),
                        journal = COALESCE(EXCLUDED.journal, papers.journal),
                        doi = COALESCE(EXCLUDED.doi, papers.doi),
                        url = COALESCE(EXCLUDED.url, papers.url),
                        pdf_url = COALESCE(EXCLUDED.pdf_url, papers.pdf_url),
                        citation_count = GREATEST(
                            COALESCE(EXCLUDED.citation_count, 0),
                            COALESCE(papers.citation_count, 0)
                        ),
                        reference_count = GREATEST(
                            COALESCE(EXCLUDED.reference_count, 0),
                            COALESCE(papers.reference_count, 0)
                        ),
                        fields_of_study = COALESCE(
                            EXCLUDED.fields_of_study, papers.fields_of_study
                        ),
                        metadata = COALESCE(EXCLUDED.metadata, papers.metadata)
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
                },
            )
            row = result.fetchone()
            actual_id = str(row[0]) if row else str(paper_id)

        logger.debug("Saved paper", paper_id=actual_id)
        return actual_id

    async def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """获取论文详情"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM papers WHERE id = :id"), {"id": paper_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def save_papers_batch(self, papers: list[dict[str, Any]]) -> list[str]:
        """批量保存论文"""
        paper_ids = []
        for paper in papers:
            paper_id = await self.save_paper(paper)
            paper_ids.append(paper_id)

        logger.info("Saved papers batch", count=len(paper_ids))
        return paper_ids

    async def get_papers_by_ids(self, paper_ids: list[str]) -> list[dict[str, Any]]:
        """批量获取论文"""
        if not paper_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM papers WHERE id = ANY(:ids)"), {"ids": paper_ids}
            )
            rows = result.fetchall()

        papers = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        order = {str(pid): idx for idx, pid in enumerate(paper_ids)}
        papers.sort(key=lambda paper: order.get(str(paper.get("id")), len(order)))
        return papers

    async def link_project_papers(
        self,
        project_id: str,
        paper_ids: list[str],
        *,
        execution_id: str | None = None,
        source_query: str | None = None,
    ) -> int:
        """Associate papers with a project and return newly inserted link count."""

        unique_ids = list(
            dict.fromkeys(str(paper_id) for paper_id in paper_ids if paper_id)
        )
        if not unique_ids:
            return 0
        async with self.session() as session:
            inserted = await session.execute(
                text("""
                    INSERT INTO project_papers (
                        project_id, paper_id, first_seen_execution_id,
                        last_seen_execution_id, source_query
                    )
                    SELECT :project_id, paper_id, :execution_id,
                           :execution_id, :source_query
                    FROM unnest(CAST(:paper_ids AS uuid[])) AS paper_id
                    ON CONFLICT (project_id, paper_id) DO NOTHING
                    RETURNING paper_id
                """),
                {
                    "project_id": project_id,
                    "paper_ids": unique_ids,
                    "execution_id": execution_id,
                    "source_query": source_query,
                },
            )
            newly_linked = len(inserted.fetchall())
            await session.execute(
                text("""
                    UPDATE project_papers
                    SET last_seen_execution_id = COALESCE(
                            :execution_id, last_seen_execution_id
                        ),
                        source_query = COALESCE(:source_query, source_query),
                        is_selected = TRUE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = :project_id
                      AND paper_id = ANY(CAST(:paper_ids AS uuid[]))
                """),
                {
                    "project_id": project_id,
                    "paper_ids": unique_ids,
                    "execution_id": execution_id,
                    "source_query": source_query,
                },
            )
        return newly_linked

    async def get_project_papers(
        self,
        project_id: str,
        *,
        limit: int = 500,
        selected_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Load only papers explicitly associated with the project."""

        selection_clause = "AND pp.is_selected = TRUE" if selected_only else ""
        async with self.session() as session:
            result = await session.execute(
                text(f"""
                    SELECT p.*
                    FROM project_papers pp
                    JOIN papers p ON p.id = pp.paper_id
                    WHERE pp.project_id = :project_id
                    {selection_clause}
                    ORDER BY pp.relevance_score DESC NULLS LAST,
                             p.citation_count DESC NULLS LAST,
                             pp.created_at ASC,
                             p.id ASC
                    LIMIT :limit
                """),  # nosec B608 - clause is a fixed internal constant
                {"project_id": project_id, "limit": max(1, min(limit, 1000))},
            )
            rows = result.fetchall()
        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_existing_embedding_paper_ids(
        self,
        paper_ids: list[str],
        *,
        model_name: str = "bge-m3",
    ) -> set[str]:
        """Return project-input paper IDs that already have an embedding."""

        if not paper_ids:
            return set()
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT DISTINCT paper_id::text
                    FROM embeddings
                    WHERE paper_id = ANY(:paper_ids)
                      AND model_name = :model_name
                """),
                {"paper_ids": paper_ids, "model_name": model_name},
            )
            return {str(row[0]) for row in result.fetchall()}

    async def get_project_evidence_cards(
        self,
        project_id: str,
        *,
        paper_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Load evidence cards scoped by project and optional paper IDs."""

        conditions = ["project_id = :project_id"]
        params: dict[str, Any] = {"project_id": project_id}
        if paper_ids:
            conditions.append("paper_id = ANY(:paper_ids)")
            params["paper_ids"] = paper_ids
        async with self.session() as session:
            result = await session.execute(
                text(f"""
                    SELECT *
                    FROM evidence_cards
                    WHERE {" AND ".join(conditions)}
                    ORDER BY created_at ASC, id ASC
                """),  # nosec B608 - conditions are fixed internal fragments
                params,
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
                },
            )

        return embedding_id

    async def save_cluster(self, cluster_data: dict[str, Any]) -> str:
        """保存聚类结果"""
        cluster_id: str = str(cluster_data.get("id") or uuid.uuid4())

        async with self.session() as session:
            await session.execute(
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
                },
            )

        logger.info("Saved cluster", cluster_id=cluster_id)
        return cluster_id

    async def delete_project_clusters(self, project_id: str) -> None:
        """删除指定项目的所有聚类及其分配关系（用于重新运行聚类前清理）"""
        async with self.session() as session:
            # 先删除 cluster_assignments（外键依赖）
            await session.execute(
                text("""
                    DELETE FROM cluster_assignments
                    WHERE cluster_id IN (
                        SELECT id FROM clusters WHERE project_id = :project_id
                    )
                """),
                {"project_id": project_id},
            )

            # 再删除 clusters
            await session.execute(
                text("DELETE FROM clusters WHERE project_id = :project_id"),
                {"project_id": project_id},
            )

        logger.info(
            "Deleted project clusters",
            project_id=project_id,
        )

    async def save_kg_entities(self, entities: list[dict[str, Any]]) -> list[str]:
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
                    },
                )
                row = result.fetchone()
                entity_ids.append(str(row[0]) if row else entity_id)

            await session.commit()

        logger.info("Saved KG entities", count=len(entity_ids))
        return entity_ids

    async def save_kg_relations(self, relations: list[dict[str, Any]]) -> list[str]:
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
                    },
                )

                relation_ids.append(relation_id)

            await session.commit()

        logger.info("Saved KG relations", count=len(relation_ids))
        return relation_ids

    async def save_evidence_card(self, card_data: dict[str, Any]) -> str:
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
                    "evidence_span": card_data.get("evidence_span")
                    or card_data.get("source_span")
                    or "",
                    "method": card_data.get("method") or "Method not specified",
                    "metric": _stringify_scalar(
                        card_data.get("metric") or card_data.get("result") or ""
                    ),
                    "limitation": card_data.get("limitation")
                    or "Limitation not specified",
                    "confidence": card_data.get("confidence", 0.0),
                    "cluster_id": card_data.get("cluster_id"),
                },
            )
            row = result.fetchone()

        actual_id = str(row[0]) if row else card_id
        logger.info("Saved evidence card", card_id=actual_id)
        return actual_id

    async def save_outline(self, outline_data: dict[str, Any]) -> str:
        """Upsert an outline and prune sections absent from its active revision."""
        outline_id: str = str(outline_data.get("id") or uuid.uuid4())

        # 转换 sections 为 JSON 字符串
        sections = outline_data.get("sections")
        if isinstance(sections, list):
            sections = json.dumps(sections)

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO outlines (id, project_id, title, sections, status, version)
                    VALUES (:id, :project_id, :title, CAST(:sections AS jsonb), :status, :version)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        sections = EXCLUDED.sections,
                        status = EXCLUDED.status,
                        version = EXCLUDED.version,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "id": outline_id,
                    "project_id": outline_data.get("project_id"),
                    "title": outline_data.get("title"),
                    "sections": sections,
                    "status": outline_data.get("status", "draft"),
                    "version": outline_data.get("version", 1),
                },
            )
            active_section_ids = [
                str(section_id)
                for section_id in outline_data.get("active_section_ids") or []
                if section_id is not None
            ]
            await session.execute(
                text("""
                    DELETE FROM written_content
                    WHERE outline_id = :outline_id
                      AND NOT (
                          section_id = ANY(CAST(:active_section_ids AS text[]))
                      )
                """),
                {
                    "outline_id": outline_id,
                    "active_section_ids": active_section_ids,
                },
            )

        logger.info("Saved outline", outline_id=outline_id)
        return outline_id

    async def save_written_section(self, section_data: dict[str, Any]) -> str:
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
                },
            )

        logger.debug("Saved written section", section_id=section_id)
        return section_id

    async def save_artifact(self, artifact_data: dict[str, Any]) -> str:
        """保存产出物"""
        artifact_id: str = str(artifact_data.get("id") or uuid.uuid4())

        # 产出物通常保存为文件，这里只记录元数据
        logger.info("Saved artifact", artifact_id=artifact_id)
        return artifact_id

    async def get_clusters_by_ids(self, cluster_ids: list[str]) -> list[dict[str, Any]]:
        """批量获取聚类详情（包含 paper_ids）"""
        if not cluster_ids:
            return []

        async with self.session() as session:
            # 获取聚类基本信息
            result = await session.execute(
                text("SELECT * FROM clusters WHERE id = ANY(:ids)"),
                {"ids": cluster_ids},
            )
            rows = result.fetchall()
            clusters = [_convert_uuid_fields(dict(row._mapping)) for row in rows]

            # 获取每个聚类的论文分配
            for cluster in clusters:
                cluster_id = cluster.get("id")
                assignments = await session.execute(
                    text(
                        "SELECT paper_id FROM cluster_assignments WHERE cluster_id = :cluster_id"
                    ),
                    {"cluster_id": cluster_id},
                )
                paper_rows = assignments.fetchall()
                cluster["paper_ids"] = [str(row[0]) for row in paper_rows]

        return clusters

    async def save_cluster_assignments(
        self, cluster_id: str, paper_ids: list[str], confidence: float = 1.0
    ) -> None:
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
                    {
                        "cluster_id": cluster_id,
                        "paper_id": paper_id,
                        "confidence": confidence,
                    },
                )

        logger.debug(
            "Saved cluster assignments",
            cluster_id=cluster_id,
            paper_count=len(paper_ids),
        )

    async def get_kg_entities_by_ids(
        self, entity_ids: list[str]
    ) -> list[dict[str, Any]]:
        """批量获取知识图谱实体"""
        if not entity_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM kg_entities WHERE id = ANY(:ids)"),
                {"ids": entity_ids},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_kg_relations_by_ids(
        self, relation_ids: list[str]
    ) -> list[dict[str, Any]]:
        """批量获取知识图谱关系"""
        if not relation_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM kg_relations WHERE id = ANY(:ids)"),
                {"ids": relation_ids},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_evidence_cards_by_ids(
        self, card_ids: list[str]
    ) -> list[dict[str, Any]]:
        """批量获取证据卡片"""
        if not card_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM evidence_cards WHERE id = ANY(:ids)"),
                {"ids": card_ids},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_written_sections_by_ids(
        self, section_ids: list[str]
    ) -> list[dict[str, Any]]:
        """批量获取已写章节"""
        if not section_ids:
            return []

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM written_content WHERE id = ANY(:ids)"),
                {"ids": section_ids},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_outline_by_id(self, outline_id: str) -> dict[str, Any] | None:
        """获取大纲详情"""
        if not outline_id:
            return None

        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM outlines WHERE id = :id"), {"id": outline_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """获取项目详情"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def save_pipeline_checkpoint(self, checkpoint_data: dict[str, Any]) -> str:
        """保存 Pipeline 检查点"""
        checkpoint_id: str = str(checkpoint_data.get("id") or uuid.uuid4())

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
                    "state_snapshot": json.dumps(
                        checkpoint_data.get("state_snapshot", {})
                    ),
                    "status": checkpoint_data.get("status", "in_progress"),
                },
            )

        logger.debug(
            "Saved pipeline checkpoint",
            checkpoint_id=checkpoint_id,
            node=checkpoint_data.get("node_name"),
        )
        return checkpoint_id

    async def get_pipeline_checkpoint(
        self, project_id: str, node_name: str
    ) -> dict[str, Any] | None:
        """获取 Pipeline 检查点"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id AND node_name = :node_name
                """),
                {"project_id": project_id, "node_name": node_name},
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_latest_checkpoint(self, project_id: str) -> dict[str, Any] | None:
        """获取项目最新的检查点"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"project_id": project_id},
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_all_checkpoints(self, project_id: str) -> list[dict[str, Any]]:
        """获取项目所有检查点（按创建时间排序）"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id
                    ORDER BY created_at ASC
                """),
                {"project_id": project_id},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def get_latest_successful_checkpoint(
        self, project_id: str
    ) -> dict[str, Any] | None:
        """获取项目最新的成功检查点（含完整 PipelineState）"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM pipeline_checkpoints
                    WHERE project_id = :project_id AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"project_id": project_id},
            )
            row = result.fetchone()

        if not row:
            return None

        cp = _convert_uuid_fields(dict(row._mapping))
        # 解析 state_snapshot JSON
        snapshot = cp.get("state_snapshot")
        if isinstance(snapshot, str):
            with suppress(json.JSONDecodeError, TypeError):
                cp["state_snapshot"] = json.loads(snapshot)
        return cp

    async def save_audit_log(self, audit_data: dict[str, Any]) -> str:
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
                },
            )

        return audit_id

    async def get_audit_logs(
        self, project_id: str, node_name: str | None = None
    ) -> list[dict[str, Any]]:
        """获取审计日志"""
        async with self.session() as session:
            if node_name:
                result = await session.execute(
                    text("""
                        SELECT * FROM pipeline_audit_log
                        WHERE project_id = :project_id AND node_name = :node_name
                        ORDER BY created_at DESC
                    """),
                    {"project_id": project_id, "node_name": node_name},
                )
            else:
                result = await session.execute(
                    text("""
                        SELECT * FROM pipeline_audit_log
                        WHERE project_id = :project_id
                        ORDER BY created_at DESC
                    """),
                    {"project_id": project_id},
                )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    async def save_project(self, project_data: dict[str, Any]) -> str:
        """保存项目"""
        import json

        project_id: str = str(project_data.get("id") or uuid.uuid4())
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
                    },
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
                    },
                )

        logger.info("Saved project", project_id=project_id)
        return project_id

    # =========================================================================
    # 用户相关方法
    # =========================================================================

    async def save_user(self, user_data: dict[str, Any]) -> str:
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
                },
            )
            row = result.fetchone()
            actual_id = str(row[0]) if row else str(user_id)

        logger.info("Saved user", user_id=actual_id)
        return actual_id

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """根据 ID 获取用户"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM users WHERE id = :id"), {"id": user_id}
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """根据邮箱获取用户"""
        async with self.session() as session:
            result = await session.execute(
                text("SELECT * FROM users WHERE email = :email"), {"email": email}
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def update_user(self, user_id: str, update_data: dict[str, Any]) -> None:
        """更新用户信息"""
        if not update_data:
            return

        # 安全修复: 白名单验证列名，防止 SQL 注入
        _ALLOWED_USER_COLUMNS = {
            "email",
            "hashed_password",
            "full_name",
            "role",
            "is_active",
            "last_login_at",
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
                text(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :id"),  # nosec B608
                params,
            )

        logger.info("Updated user", user_id=user_id)

    async def list_users(
        self, skip: int = 0, limit: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """列出所有用户"""
        async with self.session() as session:
            count_result = await session.execute(text("SELECT COUNT(*) FROM users"))
            total_raw = count_result.scalar()
            total = int(total_raw) if total_raw is not None else 0

            result = await session.execute(
                text(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
                ),
                {"limit": limit, "skip": skip},
            )
            rows = result.fetchall()

        users = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return users, total

    async def set_user_active(self, user_id: str, is_active: bool) -> None:
        """设置用户激活状态"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE users SET is_active = :is_active WHERE id = :id"),
                {"id": user_id, "is_active": is_active},
            )

    async def set_user_role(self, user_id: str, role: str) -> None:
        """设置用户角色"""
        async with self.session() as session:
            await session.execute(
                text("UPDATE users SET role = :role WHERE id = :id"),
                {"id": user_id, "role": role},
            )

    # =========================================================================
    # Refresh Token 相关方法
    # =========================================================================

    async def save_refresh_token(
        self, token_hash: str, user_id: str, expires_at: datetime
    ) -> str:
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
                },
            )

        return token_id

    async def get_refresh_token(self, token_hash: str) -> dict[str, Any] | None:
        """获取有效的 Refresh Token"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM refresh_tokens
                    WHERE token_hash = :token_hash
                      AND is_revoked = FALSE
                      AND expires_at > NOW()
                """),
                {"token_hash": token_hash},
            )
            row = result.fetchone()

        if not row:
            return None
        return _convert_uuid_fields(dict(row._mapping))

    async def revoke_refresh_token(self, token_hash: str) -> None:
        """撤销 Refresh Token"""
        async with self.session() as session:
            await session.execute(
                text(
                    "UPDATE refresh_tokens SET is_revoked = TRUE WHERE token_hash = :token_hash"
                ),
                {"token_hash": token_hash},
            )

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """撤销用户的所有 Refresh Token"""
        async with self.session() as session:
            await session.execute(
                text(
                    "UPDATE refresh_tokens SET is_revoked = TRUE WHERE user_id = :user_id"
                ),
                {"user_id": user_id},
            )

    # =========================================================================
    # 用户活动日志相关方法
    # =========================================================================

    async def log_activity(
        self,
        user_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
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
                },
            )

        return activity_id

    async def get_user_activities(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取用户活动记录"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM user_activities
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"user_id": user_id, "limit": limit, "skip": skip},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    # =========================================================================
    # 项目查询扩展
    # =========================================================================

    async def list_projects_by_user(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """列出用户的项目"""
        async with self.session() as session:
            count_result = await session.execute(
                text("SELECT COUNT(*) FROM projects WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            total_raw = count_result.scalar()
            total = int(total_raw) if total_raw is not None else 0

            result = await session.execute(
                text("""
                    SELECT * FROM projects
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"user_id": user_id, "limit": limit, "skip": skip},
            )
            rows = result.fetchall()

        projects = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return projects, total

    async def list_all_projects(
        self, skip: int = 0, limit: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """列出所有项目（管理员用），关联用户表返回用户信息"""
        async with self.session() as session:
            count_result = await session.execute(text("SELECT COUNT(*) FROM projects"))
            total_raw = count_result.scalar()
            total = int(total_raw) if total_raw is not None else 0

            result = await session.execute(
                text("""
                    SELECT p.*,
                           u.email AS user_email,
                           u.full_name AS user_name
                    FROM projects p
                    LEFT JOIN users u ON p.user_id = u.id
                    ORDER BY p.created_at DESC
                    LIMIT :limit OFFSET :skip
                """),
                {"limit": limit, "skip": skip},
            )
            rows = result.fetchall()

        projects = [_convert_uuid_fields(dict(row._mapping)) for row in rows]
        return projects, total

    async def get_system_stats(self) -> dict[str, Any]:
        """获取系统统计信息"""
        async with self.session() as session:
            users_result = await session.execute(text("SELECT COUNT(*) FROM users"))
            total_users = users_result.scalar()

            active_result = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            )
            active_users = active_result.scalar()

            projects_result = await session.execute(
                text("SELECT COUNT(*) FROM projects")
            )
            total_projects = projects_result.scalar()

            papers_result = await session.execute(text("SELECT COUNT(*) FROM papers"))
            total_papers = papers_result.scalar()

            # Pipeline runs 统计
            runs_result = await session.execute(
                text("SELECT COUNT(*) FROM pipeline_runs")
            )
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

    async def update_project_status(self, project_id: str, status: str) -> None:
        """更新项目状态"""
        async with self.session() as session:
            await session.execute(
                text(
                    "UPDATE projects SET status = :status, updated_at = NOW() WHERE id = :id"
                ),
                {"id": project_id, "status": status},
            )

        logger.info("Updated project status", project_id=project_id, status=status)

    async def get_outline_by_project_id(self, project_id: str) -> dict[str, Any] | None:
        """根据项目 ID 获取大纲"""
        async with self.session() as session:
            result = await session.execute(
                text(
                    "SELECT * FROM outlines WHERE project_id = :project_id ORDER BY version DESC LIMIT 1"
                ),
                {"project_id": project_id},
            )
            row = result.fetchone()

        if not row:
            return None

        return _convert_uuid_fields(dict(row._mapping))

    async def get_written_sections_by_project_id(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        """根据项目 ID 获取已写章节"""
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT wc.* FROM written_content wc
                    JOIN outlines o ON wc.outline_id = o.id
                    WHERE o.project_id = :project_id
                    ORDER BY wc.created_at
                """),
                {"project_id": project_id},
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    # Agent executions, decisions and tool/LLM calls are the active
    # observability write path. Legacy pipeline tables remain read-only so
    # historical usage reports continue to work after migration.

    async def create_llm_call(
        self,
        pipeline_run_id: str | None,
        node_execution_id: str | None,
        call_type: str,
        provider_name: str,
        model_name: str,
        project_id: str | None = None,
        execution_id: str | None = None,
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
        request_metadata: dict[str, Any] | None = None,
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
                        id, project_id, execution_id, pipeline_run_id,
                        node_execution_id, node_name,
                        call_type, provider_name, model_name, requested_model, upstream_model,
                        api_base_url, api_key_hint, status,
                        is_stream, latency_ms, first_token_ms,
                        input_preview, output_preview, request_metadata, retry_of,
                        input_price_per_m, output_price_per_m
                    ) VALUES (
                        :id, :project_id, :execution_id, :pipeline_run_id,
                        :node_execution_id, :node_name,
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
                    "execution_id": execution_id,
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
                    "request_metadata": json.dumps(request_metadata)
                    if request_metadata
                    else None,
                    "retry_of": retry_of,
                    "input_price_per_m": input_price_per_m,
                    "output_price_per_m": output_price_per_m,
                },
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
        provider_name: str | None = None,
        api_base_url: str | None = None,
        api_key_hint: str | None = None,
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
                        provider_name = COALESCE(:provider_name, provider_name),
                        api_base_url = COALESCE(:api_base_url, api_base_url),
                        api_key_hint = COALESCE(:api_key_hint, api_key_hint),
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
                    "provider_name": provider_name,
                    "api_base_url": api_base_url,
                    "api_key_hint": api_key_hint,
                    "input_price_per_m": input_price_per_m,
                    "output_price_per_m": output_price_per_m,
                },
            )

    async def get_provider_usage_summary(
        self,
        run_id: str | None = None,
        project_id: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
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
        """  # nosec B608

        async with self.session() as session:
            result = await session.execute(
                text(query),
                params,
            )
            rows = result.fetchall()

        return [_convert_uuid_fields(dict(row._mapping)) for row in rows]

    # =========================================================================
    # Multi-agent execution and audit persistence
    # =========================================================================

    async def create_agent_execution(
        self,
        *,
        execution_id: str,
        project_id: str,
        input_state: dict[str, Any],
    ) -> None:
        """Create the pending execution before a background task is scheduled."""

        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_executions (
                        id, project_id, agent_name, status, input_state, started_at
                    )
                    VALUES (
                        :id, :project_id, 'orchestrator', 'pending',
                        CAST(:input_state AS jsonb), CURRENT_TIMESTAMP
                    )
                """),
                {
                    "id": execution_id,
                    "project_id": project_id,
                    "input_state": json.dumps(input_state, ensure_ascii=False),
                },
            )

    async def update_agent_execution(
        self,
        execution_id: str,
        status: str,
        *,
        output_state: dict[str, Any] | None = None,
        quality_score: float | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update one execution using a single canonical lifecycle."""

        terminal = status in {"succeeded", "failed", "interrupted", "cancelled"}
        async with self.session() as session:
            await session.execute(
                text("""
                    UPDATE agent_executions
                    SET status = :status,
                        output_state = COALESCE(
                            CAST(:output_state AS jsonb),
                            output_state
                        ),
                        quality_score = COALESCE(
                            CAST(:quality_score AS double precision),
                            quality_score
                        ),
                        error_message = :error_message,
                        finished_at = CASE
                            WHEN CAST(:terminal AS boolean) THEN CURRENT_TIMESTAMP
                            ELSE NULL
                        END,
                        duration_ms = CASE
                            WHEN CAST(:terminal AS boolean) THEN
                                (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000)::bigint
                            ELSE duration_ms
                        END
                    WHERE id = :id
                """),
                {
                    "id": execution_id,
                    "status": status,
                    "output_state": (
                        json.dumps(output_state, ensure_ascii=False)
                        if output_state is not None
                        else None
                    ),
                    "quality_score": quality_score,
                    "error_message": error_message,
                    "terminal": terminal,
                },
            )

    async def get_latest_agent_execution(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:
        async with self.session() as session:
            result = await session.execute(
                text("""
                    SELECT *
                    FROM agent_executions
                    WHERE project_id = :project_id
                    ORDER BY started_at DESC, id DESC
                    LIMIT 1
                """),
                {"project_id": project_id},
            )
            row = result.fetchone()
        return _convert_uuid_fields(dict(row._mapping)) if row else None

    async def record_agent_decision(
        self,
        *,
        execution_id: str,
        project_id: str,
        agent_name: str,
        decision: str,
        reason: str | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_decisions (
                        id, execution_id, project_id, agent_name, decision, reason
                    )
                    VALUES (
                        :id, :execution_id, :project_id, :agent_name,
                        :decision, :reason
                    )
                """),
                {
                    "id": decision_id,
                    "execution_id": execution_id,
                    "project_id": project_id,
                    "agent_name": agent_name,
                    "decision": decision,
                    "reason": reason,
                },
            )
        return decision_id

    async def record_agent_tool_call(
        self,
        *,
        execution_id: str,
        project_id: str,
        agent_name: str,
        tool_name: str,
        input_summary: str | None,
        output_summary: str | None,
        duration_ms: int,
        status: str,
        error_message: str | None = None,
    ) -> str:
        call_id = str(uuid.uuid4())
        async with self.session() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_tool_calls (
                        id, execution_id, project_id, agent_name, tool_name,
                        input_summary, output_summary, duration_ms, status,
                        error_message
                    )
                    VALUES (
                        :id, :execution_id, :project_id, :agent_name, :tool_name,
                        :input_summary, :output_summary, :duration_ms, :status,
                        :error_message
                    )
                """),
                {
                    "id": call_id,
                    "execution_id": execution_id,
                    "project_id": project_id,
                    "agent_name": agent_name,
                    "tool_name": tool_name,
                    "input_summary": input_summary,
                    "output_summary": output_summary,
                    "duration_ms": duration_ms,
                    "status": status,
                    "error_message": error_message,
                },
            )
        return call_id

    async def cleanup_stale_agent_executions(self) -> int:
        """清理过期的 Agent 执行记录

        将 status='running' 的所有 agent_executions 标记为 'interrupted'。
        用于容器重启后的状态清理。
        类似 main.py 中对 projects 表的清理逻辑。

        Returns
        -------
        int
            被清理的记录数。
        """
        async with self.session() as session:
            # 先统计受影响的记录数
            count_result = await session.execute(
                text("""
                    SELECT COUNT(*) FROM agent_executions
                    WHERE status IN ('running', 'pending')
                """),
            )
            count_row = count_result.fetchone()
            affected: int = int(count_row[0]) if count_row else 0

            if affected > 0:
                await session.execute(
                    text("""
                        UPDATE agent_executions
                        SET status = 'interrupted',
                            finished_at = CURRENT_TIMESTAMP,
                            error_message = 'Server restart: execution interrupted'
                        WHERE status IN ('running', 'pending')
                    """),
                )
                logger.info(
                    "Cleaned stale agent executions",
                    count=affected,
                )

        return affected


# 全局数据库实例
_db_service: DatabaseService | None = None


def get_database() -> DatabaseService:
    """获取数据库服务单例"""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
    return _db_service


async def close_database() -> None:
    """关闭数据库连接"""
    global _db_service
    if _db_service is not None:
        await _db_service.close()
        _db_service = None
