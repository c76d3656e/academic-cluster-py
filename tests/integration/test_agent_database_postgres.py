"""Real PostgreSQL coverage for project-scoped Agent persistence."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from academic_cluster.api.main import _cleanup_stale_executions
from academic_cluster.services.database import DatabaseService
from academic_cluster.services.vector_store import VectorStoreService

pytestmark = pytest.mark.integration


async def _new_project(database: DatabaseService, label: str) -> str:
    return await database.save_project(
        {
            "name": f"integration-{label}-{uuid.uuid4()}",
            "description": "disposable PostgreSQL integration project",
            "query": label,
            "config": {"scope": label, "nested": {"enabled": True}},
        }
    )


async def _new_paper(database: DatabaseService, label: str) -> str:
    suffix = uuid.uuid4().hex
    return await database.save_paper(
        {
            "external_id": f"integration:{label}:{suffix}",
            "source": "integration-test",
            "title": f"Paper {label} {suffix}",
            "abstract": f"Abstract isolated to {label}",
            "authors": [{"name": "Integration Test"}],
            "fields_of_study": ["Testing"],
            "metadata": {"label": label},
        }
    )


async def test_project_papers_and_evidence_are_strictly_isolated(
    agent_database: DatabaseService,
) -> None:
    """A shared paper may belong to both projects without leaking other papers."""

    project_a = await _new_project(agent_database, "project-a")
    project_b = await _new_project(agent_database, "project-b")
    paper_a = await _new_paper(agent_database, "paper-a")
    paper_b = await _new_paper(agent_database, "paper-b")
    shared_paper = await _new_paper(agent_database, "shared")

    project_a_new = await agent_database.link_project_papers(
        project_a,
        [paper_a, shared_paper, paper_a],
        source_query="query-a",
    )
    project_b_new = await agent_database.link_project_papers(
        project_b,
        [paper_b, shared_paper],
        source_query="query-b",
    )
    project_a_repeat = await agent_database.link_project_papers(
        project_a,
        [paper_a, shared_paper],
        source_query="query-a-repeat",
    )

    assert project_a_new == 2
    assert project_b_new == 2
    assert project_a_repeat == 0

    project_a_papers = await agent_database.get_project_papers(project_a)
    project_b_papers = await agent_database.get_project_papers(project_b)
    assert {paper["id"] for paper in project_a_papers} == {paper_a, shared_paper}
    assert {paper["id"] for paper in project_b_papers} == {paper_b, shared_paper}

    await agent_database.save_evidence_card(
        {
            "project_id": project_a,
            "paper_id": paper_a,
            "claim": "project A claim",
            "evidence_span": "A-only evidence",
            "confidence": 0.9,
        }
    )
    await agent_database.save_evidence_card(
        {
            "project_id": project_b,
            "paper_id": paper_b,
            "claim": "project B claim",
            "evidence_span": "B-only evidence",
            "confidence": 0.8,
        }
    )

    project_a_cards = await agent_database.get_project_evidence_cards(
        project_a,
        paper_ids=[paper_a, shared_paper],
    )
    project_b_cards = await agent_database.get_project_evidence_cards(project_b)
    assert [(card["paper_id"], card["claim"]) for card in project_a_cards] == [
        (paper_a, "project A claim")
    ]
    assert [(card["paper_id"], card["claim"]) for card in project_b_cards] == [
        (paper_b, "project B claim")
    ]


async def test_outline_revision_prunes_removed_written_sections(
    agent_database: DatabaseService,
) -> None:
    project_id = await _new_project(agent_database, "outline-pruning")
    outline_id = str(uuid.uuid4())
    await agent_database.save_outline(
        {
            "id": outline_id,
            "project_id": project_id,
            "title": "Initial outline",
            "sections": [{"id": "keep"}, {"id": "remove"}],
            "active_section_ids": ["keep", "remove"],
        }
    )
    for section_id in ("keep", "remove"):
        await agent_database.save_written_section(
            {
                "outline_id": outline_id,
                "section_id": section_id,
                "content": section_id,
            }
        )

    await agent_database.save_outline(
        {
            "id": outline_id,
            "project_id": project_id,
            "title": "Revised outline",
            "sections": [{"id": "keep"}],
            "active_section_ids": ["keep"],
        }
    )

    sections = await agent_database.get_written_sections_by_project_id(project_id)
    assert [section["section_id"] for section in sections] == ["keep"]


async def test_embedding_uuid_array_query_accepts_public_string_ids(
    agent_database: DatabaseService,
) -> None:
    """String IDs from API state bind correctly to PostgreSQL UUID arrays."""

    paper_with_embedding = await _new_paper(agent_database, "embedded")
    paper_without_embedding = await _new_paper(agent_database, "not-embedded")
    vector = "[" + ",".join(["0.1"] * 1024) + "]"
    async with agent_database.session() as session:
        await session.execute(
            text("""
                INSERT INTO embeddings (paper_id, model_name, vector, dimensions)
                VALUES (:paper_id, 'integration-model', CAST(:vector AS vector), 1024)
            """),
            {"paper_id": paper_with_embedding, "vector": vector},
        )

    existing = await agent_database.get_existing_embedding_paper_ids(
        [paper_with_embedding, paper_without_embedding],
        model_name="integration-model",
    )
    assert existing == {paper_with_embedding}


async def test_knn_graph_never_mixes_embedding_model_spaces(
    agent_database: DatabaseService,
) -> None:
    paper_a = await _new_paper(agent_database, "model-space-a")
    paper_b = await _new_paper(agent_database, "model-space-b")
    paper_c = await _new_paper(agent_database, "model-space-c")
    vector = "[" + ",".join(["0.1"] * 1024) + "]"
    async with agent_database.session() as session:
        await session.execute(
            text("""
                INSERT INTO embeddings (paper_id, model_name, vector, dimensions)
                VALUES
                    (:paper_a, 'model-a', CAST(:vector AS vector), 1024),
                    (:paper_b, 'model-a', CAST(:vector AS vector), 1024),
                    (:paper_a, 'model-b', CAST(:vector AS vector), 1024),
                    (:paper_c, 'model-b', CAST(:vector AS vector), 1024)
            """),
            {
                "paper_a": paper_a,
                "paper_b": paper_b,
                "paper_c": paper_c,
                "vector": vector,
            },
        )

    store = object.__new__(VectorStoreService)
    store.db = agent_database
    edges = await store.get_knn_graph(
        [paper_a, paper_b, paper_c],
        k=2,
        threshold=0.9,
        model_name="model-a",
    )

    assert edges
    assert {
        endpoint for edge in edges for endpoint in (edge["source"], edge["target"])
    } == {paper_a, paper_b}


async def test_agent_execution_lifecycle_json_and_audit_logs(
    agent_database: DatabaseService,
) -> None:
    """Lifecycle state and audit payloads round-trip through canonical tables."""

    project_id = await _new_project(agent_database, "execution")
    execution_id = str(uuid.uuid4())
    input_state = {
        "topic": "多智能体数据库恢复",
        "queries": ["checkpoint", "project isolation"],
        "options": {"retry": 2, "enabled": True},
    }
    await agent_database.create_agent_execution(
        execution_id=execution_id,
        project_id=project_id,
        input_state=input_state,
    )

    pending = await agent_database.get_latest_agent_execution(project_id)
    assert pending is not None
    assert pending["id"] == execution_id
    assert pending["status"] == "pending"
    assert pending["input_state"] == input_state

    with pytest.raises(IntegrityError):
        await agent_database.create_agent_execution(
            execution_id=str(uuid.uuid4()),
            project_id=project_id,
            input_state={"duplicate": True},
        )

    await agent_database.update_agent_execution(execution_id, "running")
    decision_id = await agent_database.record_agent_decision(
        execution_id=execution_id,
        project_id=project_id,
        agent_name="supervisor",
        decision="continue_to_analysis",
        reason="coverage threshold met",
    )
    tool_call_id = await agent_database.record_agent_tool_call(
        execution_id=execution_id,
        project_id=project_id,
        agent_name="research",
        tool_name="search_papers",
        input_summary='{"query":"checkpoint"}',
        output_summary='{"papers":2}',
        duration_ms=17,
        status="success",
    )
    llm_call_id = await agent_database.create_llm_call(
        pipeline_run_id=None,
        node_execution_id=None,
        project_id=project_id,
        execution_id=execution_id,
        node_name="analysis",
        call_type="llm",
        provider_name="integration-provider",
        model_name="integration-model",
        input_preview="project-scoped prompt",
        request_metadata={"agent_phase": "analysis"},
    )
    await agent_database.finish_llm_call(
        llm_call_id,
        prompt_tokens=3,
        completion_tokens=5,
        latency_ms=7,
        provider_name="selected-provider",
        api_base_url="https://selected.invalid/v1",
        api_key_hint="selected-key",
    )
    output_state = {
        "status": "failed",
        "errors": ["review score below threshold"],
        "references": {"1": "paper-a"},
    }
    await agent_database.update_agent_execution(
        execution_id,
        "failed",
        output_state=output_state,
        quality_score=62.5,
        error_message="review score below threshold",
    )

    failed = await agent_database.get_latest_agent_execution(project_id)
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["output_state"] == output_state
    assert failed["quality_score"] == 62.5
    assert failed["finished_at"] is not None
    assert failed["duration_ms"] >= 0

    async with agent_database.session() as session:
        decision = (
            (
                await session.execute(
                    text("SELECT * FROM agent_decisions WHERE id = :id"),
                    {"id": decision_id},
                )
            )
            .mappings()
            .one()
        )
        tool_call = (
            (
                await session.execute(
                    text("SELECT * FROM agent_tool_calls WHERE id = :id"),
                    {"id": tool_call_id},
                )
            )
            .mappings()
            .one()
        )
        llm_call = (
            (
                await session.execute(
                    text("SELECT * FROM llm_calls WHERE id = :id"),
                    {"id": llm_call_id},
                )
            )
            .mappings()
            .one()
        )

    assert str(decision["execution_id"]) == execution_id
    assert str(decision["project_id"]) == project_id
    assert decision["decision"] == "continue_to_analysis"
    assert decision["reason"] == "coverage threshold met"
    assert str(tool_call["execution_id"]) == execution_id
    assert str(tool_call["project_id"]) == project_id
    assert tool_call["tool_name"] == "search_papers"
    assert tool_call["duration_ms"] == 17
    assert tool_call["status"] == "success"
    assert str(llm_call["execution_id"]) == execution_id
    assert str(llm_call["project_id"]) == project_id
    assert llm_call["pipeline_run_id"] is None
    assert llm_call["node_execution_id"] is None
    assert llm_call["provider_name"] == "selected-provider"
    assert llm_call["api_base_url"] == "https://selected.invalid/v1"
    assert llm_call["api_key_hint"] == "selected-key"
    assert llm_call["node_name"] == "analysis"
    assert llm_call["total_tokens"] == 8


async def test_startup_reconciles_stale_pipeline_and_agent_rows(
    agent_database: DatabaseService,
) -> None:
    project_id = await _new_project(agent_database, "stale-startup")
    execution_id = str(uuid.uuid4())
    pipeline_run_id = str(uuid.uuid4())
    await agent_database.update_project_status(project_id, "running:agent:analysis")
    await agent_database.create_agent_execution(
        execution_id=execution_id,
        project_id=project_id,
        input_state={"topic": "stale"},
    )
    async with agent_database.session() as session:
        await session.execute(
            text("""
                INSERT INTO pipeline_runs (id, project_id, topic, status)
                VALUES (:id, :project_id, 'stale', 'running')
            """),
            {"id": pipeline_run_id, "project_id": project_id},
        )

    await _cleanup_stale_executions(agent_database)

    project = await agent_database.get_project(project_id)
    execution = await agent_database.get_latest_agent_execution(project_id)
    async with agent_database.session() as session:
        pipeline_status = await session.scalar(
            text("SELECT status FROM pipeline_runs WHERE id = :id"),
            {"id": pipeline_run_id},
        )

    assert project is not None
    assert project["status"] == "interrupted"
    assert execution is not None
    assert execution["status"] == "interrupted"
    assert pipeline_status == "interrupted"
