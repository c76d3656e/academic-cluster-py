from academic_cluster.graphs.nodes.community_memory import synthesize_community_memory


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
