from academic_cluster.graphs.nodes.outline_generation import (
    _normalize_outline_sections,
    _normalize_outline_word_budget,
)


def test_normalize_outline_sections_adds_community_memory_fields():
    outline = {
        "title": "Review",
        "sections": [
            {
                "name": "section_0",
                "title": "Methods",
                "description": "Compare methods",
                "target_words": 1000,
                "key_clusters": ["cluster-1"],
            }
        ],
    }
    memories = [
        {
            "cluster_id": "cluster-1",
            "method_families": ["Method A"],
            "key_claims": [{"paper_id": "p1", "claim": "Claim A"}],
            "limitations": ["Limited benchmark"],
            "future_directions": ["Improve evaluation"],
            "proof_ids": [{"type": "evidence_card", "id": "card-1", "paper_id": "p1"}],
            "metadata": {
                "coherence_assessment": {"score": 0.8, "rationale": "coherent"},
                "topic_relevance": {"score": 0.9, "rationale": "relevant"},
                "evidence_gaps": ["Missing cross-domain benchmark"],
            },
        }
    ]

    normalized = _normalize_outline_sections(outline, memories)
    section = normalized["sections"][0]

    assert section["target_communities"] == ["cluster-1"]
    assert section["method_families"] == ["Method A"]
    assert section["expected_claims"][0]["claim"] == "Claim A"
    assert section["limitations_to_cover"] == ["Limited benchmark"]
    assert section["future_directions_to_cover"] == ["Improve evaluation"]
    assert section["proof_ids"][0]["id"] == "card-1"
    assert section["community_synthesis"][0]["topic_relevance"]["score"] == 0.9
    assert "previous_section_dependency" in section
    assert "next_section_dependency" in section


def test_normalize_outline_word_budget_preserves_relative_agent_weights():
    outline = {
        "title": "Review",
        "sections": [
            {"name": "section_0", "target_words": 2000},
            {"name": "section_1", "target_words": 4000},
            {"name": "section_2", "target_words": 6000},
        ],
    }

    normalized = _normalize_outline_word_budget(outline, total_target_words=12000)
    targets = [section["target_words"] for section in normalized["sections"]]

    assert sum(targets) == 12000
    assert targets[0] < targets[1] < targets[2]
    assert normalized["total_target_words"] == 12000


def test_normalize_outline_sections_can_apply_total_word_budget():
    outline = {
        "title": "Review",
        "sections": [
            {"name": "section_0", "target_words": 2000},
            {"name": "section_1", "target_words": 2000},
            {"name": "section_2", "target_words": 2000},
            {"name": "section_3", "target_words": 2000},
        ],
    }

    normalized = _normalize_outline_sections(outline, [], total_target_words=12000)

    assert sum(section["target_words"] for section in normalized["sections"]) == 12000
