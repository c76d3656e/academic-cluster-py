from academic_cluster.graphs.nodes.community_memory import synthesize_community_memory
from academic_cluster.graphs.nodes.community_memory import community_memory_node


def test_synthesize_community_memory_contains_required_fields():
    memory = synthesize_community_memory(
        project_id="project-1",
        cluster={"id": "cluster-1", "name": "cluster", "paper_ids": ["p1", "p2"]},
        papers=[
            {"id": "p1", "title": "Foundation Paper", "citation_count": 100, "publication_date": "2014-01-01"},
            {"id": "p2", "title": "Frontier Paper", "citation_count": 10, "publication_date": "2025-01-01"},
        ],
        evidence_cards=[
            {
                "id": "card-1",
                "paper_id": "p1",
                "claim": "Claim one",
                "method": "Method A",
                "limitation": "Limited evaluation",
                "confidence": 0.8,
            }
        ],
        kg_entities=[
            {"id": "e1", "name": "Method A", "entity_type": "method", "paper_ids": ["p1"]},
            {"id": "e2", "name": "Open Problem", "entity_type": "limitation", "paper_ids": ["p2"]},
        ],
        kg_relations=[
            {"id": "r1", "relation_type": "addresses_limitation", "paper_ids": ["p1", "p2"]},
        ],
    )

    assert memory["cluster_id"] == "cluster-1"
    assert memory["summary"]
    assert "Method A" in memory["method_families"]
    assert memory["key_claims"][0]["evidence_card_id"] == "card-1"
    assert memory["limitations"]
    assert memory["future_directions"]
    assert memory["foundation_papers"] == ["p1"]
    assert memory["frontier_papers"] == ["p2"]
    assert any(proof["id"] == "card-1" for proof in memory["proof_ids"])


def test_synthesize_community_memory_marks_deterministic_structure():
    memory = synthesize_community_memory(
        project_id="project-1",
        cluster={"id": "cluster-1", "name": "cluster", "paper_ids": ["p1"]},
        papers=[{"id": "p1", "title": "Paper", "publication_date": "2020-01-01"}],
        evidence_cards=[
            {
                "id": "card-1",
                "paper_id": "p1",
                "claim": "A verified claim",
                "evidence_span": "Abstract-backed evidence.",
                "method": "Graph method",
                "limitation": "Sparse validation",
            }
        ],
        kg_entities=[],
        kg_relations=[],
    )

    assert memory["key_claims"][0]["claim"] == "A verified claim"
    assert memory["future_directions"][0].startswith("Address limitation")
    assert memory["metadata"]["evidence_card_count"] == 1


class _FakeCommunityMemoryDb:
    def __init__(self):
        self.saved = []

    async def get_clusters_by_ids(self, ids):
        return [{"id": "cluster-1", "name": "cluster", "paper_ids": ["p1"]}]

    async def get_papers_by_ids(self, ids):
        return [{"id": "p1", "title": "Paper", "abstract": "Abstract", "publication_date": "2024-01-01"}]

    async def get_evidence_cards_by_ids(self, ids):
        return [{"id": "card-1", "paper_id": "p1", "claim": "Claim", "limitation": "Limit"}]

    async def get_kg_entities_by_ids(self, ids):
        return []

    async def get_kg_relations_by_ids(self, ids):
        return []

    async def save_community_memory(self, memory):
        self.saved.append(memory)
        return "memory-1"


async def test_community_memory_node_falls_back_when_llm_times_out(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    db = _FakeCommunityMemoryDb()

    async def never_returns(**kwargs):
        await asyncio.sleep(5)

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.enrich_community_memory_with_llm",
        never_returns,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.get_llm_available_slots",
        lambda default=10: 10,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.send_progress",
        noop_progress,
    )

    state = SimpleNamespace(
        project_id="project-1",
        query="topic",
        cluster_ids=["cluster-1"],
        core_paper_ids=["p1"],
        auxiliary_paper_ids=[],
        evidence_card_ids=["card-1"],
        kg_entity_ids=[],
        kg_relation_ids=[],
        config={"community_memory_timeout_s": 0, "community_memory_concurrency": 4},
    )

    result = await community_memory_node(state)

    assert result["community_memory_ids"] == ["memory-1"]
    assert result["status"] == "community_memory_synthesized"
    assert db.saved[0]["metadata"]["synthesis_mode"] == "deterministic_fallback"
    assert "timed out" in db.saved[0]["metadata"]["llm_error"]


async def test_community_memory_node_can_skip_llm_by_limit(monkeypatch):
    from types import SimpleNamespace

    db = _FakeCommunityMemoryDb()
    called = False

    async def should_not_run(**kwargs):
        nonlocal called
        called = True
        return {}

    async def noop_progress(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.enrich_community_memory_with_llm",
        should_not_run,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.get_llm_available_slots",
        lambda default=10: 10,
    )
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.community_memory.send_progress",
        noop_progress,
    )

    state = SimpleNamespace(
        project_id="project-1",
        query="topic",
        cluster_ids=["cluster-1"],
        core_paper_ids=["p1"],
        auxiliary_paper_ids=[],
        evidence_card_ids=["card-1"],
        kg_entity_ids=[],
        kg_relation_ids=[],
        config={"community_memory_llm_limit": 0},
    )

    result = await community_memory_node(state)

    assert result["community_memory_ids"] == ["memory-1"]
    assert called is False
    assert db.saved[0]["metadata"]["llm_skipped"] == "community_memory_llm_limit"
