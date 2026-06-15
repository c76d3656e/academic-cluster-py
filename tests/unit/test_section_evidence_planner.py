from academic_cluster.services.citation_planner import (
    CandidateSelectionSource,
    SectionCitationPlan,
)
from academic_cluster.services.section_evidence_planner import (
    cards_from_support_matrix,
    plan_section_evidence,
)


def test_plan_section_evidence_prefers_section_relevant_candidates():
    sections = [
        {
            "title": "Agent planning and tool use",
            "description": "Compare autonomous agent planning, memory, and tool-use methods.",
            "target_communities": ["1"],
        }
    ]
    plans = [
        SectionCitationPlan(
            section_index=0,
            section_title="Agent planning and tool use",
            key_clusters=["1"],
            candidate_paper_ids=["p-agent", "p-driving", "p-hardware"],
            candidate_details=[
                {
                    "paper_id": "p-agent",
                    "cluster_id": "1",
                    "is_core": True,
                    "source": CandidateSelectionSource.COMMUNITY_CORE.value,
                },
                {
                    "paper_id": "p-driving",
                    "cluster_id": "2",
                    "is_core": True,
                    "source": CandidateSelectionSource.GLOBAL_CORE.value,
                },
                {
                    "paper_id": "p-hardware",
                    "cluster_id": "3",
                    "is_core": True,
                    "source": CandidateSelectionSource.GLOBAL_CORE.value,
                },
            ],
        )
    ]
    papers = {
        "p-agent": {
            "id": "p-agent",
            "title": "Planning and tool use in autonomous LLM agents",
            "abstract": "Agent memory, planning, tool use, and reflection.",
        },
        "p-driving": {
            "id": "p-driving",
            "title": "Lane changing in autonomous driving",
            "abstract": "Vehicle control and traffic safety.",
        },
        "p-hardware": {
            "id": "p-hardware",
            "title": "Photonic VLSI hardware",
            "abstract": "Quantum devices and chip layout.",
        },
    }
    evidence_cards = [
        {
            "id": "card-agent",
            "paper_id": "p-agent",
            "claim": "Agent systems combine planning, memory, and tool use.",
            "evidence_span": "The paper evaluates planning and tool-use agents.",
            "method": "agent planning",
            "confidence": 0.9,
        }
    ]
    memories = [
        {
            "cluster_id": "1",
            "summary": "This community studies autonomous LLM agents, planning, memory, and tools.",
            "method_families": ["agent planning"],
            "key_claims": [{"paper_id": "p-agent", "claim": "planning and tool use"}],
        }
    ]
    clusters = [
        {"id": "1", "paper_ids": ["p-agent"]},
        {"id": "2", "paper_ids": ["p-driving"]},
        {"id": "3", "paper_ids": ["p-hardware"]},
    ]

    filtered, evidence_plan = plan_section_evidence(
        topic="LLM-based autonomous agents",
        sections=sections,
        citation_plans=plans,
        evidence_cards=evidence_cards,
        community_memories=memories,
        paper_map=papers,
        clusters=clusters,
        max_references_per_section=2,
        min_references_per_section=1,
    )

    assert filtered[0].candidate_paper_ids[0] == "p-agent"
    assert "p-hardware" not in filtered[0].candidate_paper_ids
    matrix = evidence_plan[0]["support_matrix"]
    assert matrix[0]["paper_id"] == "p-agent"
    cards = cards_from_support_matrix(matrix)
    assert cards[0]["id"] == "card-agent"
