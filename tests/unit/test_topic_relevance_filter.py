"""Unit tests for topic_relevance_filter node."""

from types import SimpleNamespace

import pytest

from academic_cluster.graphs.nodes.topic_relevance_filter import (
    _parse_json_object,
    topic_relevance_filter_node,
)

# =============================================================================
# Pure function tests
# =============================================================================


def test_parse_json_object_strips_code_fences():
    raw = '```json\n[{"paper_id": "p1", "relevance_score": 0.9}]\n```'
    result = _parse_json_object(raw)
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_json_object_extracts_json_from_text():
    raw = 'Here is the result: {"assessments": [{"paper_id": "p1"}]} done.'
    result = _parse_json_object(raw)
    assert isinstance(result, dict)
    assert len(result["assessments"]) == 1


def test_parse_json_object_handles_array():
    raw = '[{"paper_id": "p1", "relevance_score": 0.9}]'
    result = _parse_json_object(raw)
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_json_object_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        _parse_json_object("")


# =============================================================================
# Fake DB for async node tests
# =============================================================================


class _FakeDb:
    def __init__(self, papers: list[dict]):
        self._papers = {p["id"]: p for p in papers}

    async def get_papers_by_ids(self, ids):
        return [self._papers[pid] for pid in ids if pid in self._papers]


# =============================================================================
# Node tests
# =============================================================================


async def test_filter_removes_low_relevance(monkeypatch):
    """Papers scored below threshold should be removed from core/aux."""
    papers = [
        {"id": "p1", "title": "Relevant", "abstract": "A"},
        {"id": "p2", "title": "Irrelevant", "abstract": "B"},
        {"id": "p3", "title": "Borderline", "abstract": "C"},
        {"id": "p4", "title": "Good aux", "abstract": "D"},
    ]
    db = _FakeDb(papers)

    async def fake_evaluate(paper, topic, timeout_s):
        scores = {"p1": 0.9, "p2": 0.1, "p3": 0.5, "p4": 0.8}
        return paper["id"], scores.get(paper["id"], 1.0)

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="machine learning",
        core_paper_ids=["p1", "p2"],
        auxiliary_paper_ids=["p3", "p4"],
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 160,
        },
    )

    result = await topic_relevance_filter_node(state)

    # p2 (score 0.1) should be filtered out
    assert "p2" not in result["core_paper_ids"]
    # p1 stays in core, p3/p4 backfill from aux because core_reference_count=160
    assert "p1" in result["core_paper_ids"]
    assert "p3" in result["core_paper_ids"]
    assert "p4" in result["core_paper_ids"]
    assert result["topic_filtered_count"] == 1  # only p2 removed
    assert result["topic_relevance_scores"]["p2"] == 0.1


async def test_filter_keeps_all_relevant(monkeypatch):
    """All papers above threshold should be preserved."""
    papers = [
        {"id": "p1", "title": "A", "abstract": ""},
        {"id": "p2", "title": "B", "abstract": ""},
    ]
    db = _FakeDb(papers)

    async def fake_evaluate(paper, topic, timeout_s):
        scores = {"p1": 0.9, "p2": 0.8}
        return paper["id"], scores.get(paper["id"], 1.0)

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        core_paper_ids=["p1", "p2"],
        auxiliary_paper_ids=[],
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 160,
        },
    )

    result = await topic_relevance_filter_node(state)

    assert result["core_paper_ids"] == ["p1", "p2"]
    assert result["topic_filtered_count"] == 0


async def test_backfill_from_auxiliary(monkeypatch):
    """When core drops below target, backfill from auxiliary."""
    core = [f"c{i}" for i in range(5)]
    aux = [f"a{i}" for i in range(10)]
    papers = [{"id": pid, "title": "", "abstract": ""} for pid in core + aux]
    db = _FakeDb(papers)

    scores = dict.fromkeys(core, 0.1)
    scores.update(dict.fromkeys(aux, 0.9))

    async def fake_evaluate(paper, topic, timeout_s):
        return paper["id"], scores.get(paper["id"], 1.0)

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        core_paper_ids=core,
        auxiliary_paper_ids=aux,
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 10,
        },
    )

    result = await topic_relevance_filter_node(state)

    assert len(result["core_paper_ids"]) == 10
    assert all(pid.startswith("a") for pid in result["core_paper_ids"])


async def test_filter_degrades_on_total_failure(monkeypatch):
    """All LLM failures should preserve original lists."""
    papers = [{"id": "p1", "title": "A", "abstract": ""}]
    db = _FakeDb(papers)

    async def failing_evaluate(paper, topic, timeout_s):
        raise RuntimeError("LLM unavailable")

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        failing_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        core_paper_ids=["p1"],
        auxiliary_paper_ids=[],
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 160,
        },
    )

    result = await topic_relevance_filter_node(state)

    assert result["status"] == "relevance_filter_degraded"
    assert result["topic_filtered_count"] == 0


async def test_unassessed_papers_filtered_out(monkeypatch):
    """Papers that fail evaluation default to score 0.0 and should be filtered."""
    papers = [
        {"id": "p1", "title": "Good", "abstract": ""},
        {"id": "p2", "title": "Failed", "abstract": ""},
    ]
    db = _FakeDb(papers)

    async def partial_evaluate(paper, topic, timeout_s):
        if paper["id"] == "p2":
            raise RuntimeError("LLM timeout")
        return paper["id"], 0.9

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        partial_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        core_paper_ids=["p1", "p2"],
        auxiliary_paper_ids=[],
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 2,
        },
    )

    result = await topic_relevance_filter_node(state)

    assert "p1" in result["core_paper_ids"]
    assert "p2" not in result["core_paper_ids"]
    assert result["topic_filtered_count"] == 1


async def test_filter_skips_when_disabled(monkeypatch):
    """When topic_relevance_enabled=false, return empty dict."""
    called = False

    async def should_not_run(paper, topic, timeout_s):
        nonlocal called
        called = True
        return paper["id"], 1.0

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        should_not_run,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        core_paper_ids=["p1"],
        auxiliary_paper_ids=[],
        config={"topic_relevance_enabled": False},
    )

    result = await topic_relevance_filter_node(state)

    assert result == {}
    assert called is False


async def test_state_default_values():
    """New state fields should have correct defaults."""
    from academic_cluster.graphs.state import PipelineState

    state = PipelineState(project_id="test", query="q")
    assert state.topic_relevance_scores == {}
    assert state.topic_filtered_count == 0


async def test_pre_clustering_filters_paper_ids(monkeypatch):
    """Pre-clustering mode: filter paper_ids when core/aux are empty."""
    papers = [
        {"id": "p1", "title": "Relevant", "abstract": ""},
        {"id": "p2", "title": "Irrelevant", "abstract": ""},
        {"id": "p3", "title": "Good", "abstract": ""},
    ]
    db = _FakeDb(papers)

    async def fake_evaluate(paper, topic, timeout_s):
        scores = {"p1": 0.9, "p2": 0.1, "p3": 0.8}
        return paper["id"], scores.get(paper["id"], 1.0)

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter._evaluate_single_paper",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.send_progress",
        noop_progress,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.topic_relevance_filter.get_llm_available_slots",
        lambda **_: 10,
    )

    state = SimpleNamespace(
        project_id="proj-1",
        query="topic",
        paper_ids=["p1", "p2", "p3"],
        core_paper_ids=[],
        auxiliary_paper_ids=[],
        config={
            "topic_relevance_enabled": True,
            "topic_relevance_threshold": 0.4,
            "topic_relevance_concurrency": 4,
            "topic_relevance_timeout_s": 90,
            "core_reference_count": 160,
        },
    )

    result = await topic_relevance_filter_node(state)

    assert "p1" in result["paper_ids"]
    assert "p2" not in result["paper_ids"]
    assert "p3" in result["paper_ids"]
    assert result["topic_filtered_count"] == 1
    assert "core_paper_ids" not in result
    assert "auxiliary_paper_ids" not in result
