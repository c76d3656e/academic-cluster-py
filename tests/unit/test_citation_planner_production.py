"""Citation planning must accept the UUID cluster IDs produced in production."""

from academic_cluster.services.citation_planner import plan_review_citations


def test_fallback_sections_use_uuid_cluster_ids_without_reindexing() -> None:
    cluster_a = "11111111-1111-1111-1111-111111111111"
    cluster_b = "22222222-2222-2222-2222-222222222222"
    papers = [
        {"id": "paper-a1"},
        {"id": "paper-a2"},
        {"id": "paper-b1"},
        {"id": "paper-b2"},
    ]
    clusters = [
        {"id": cluster_a, "paper_ids": ["paper-a1", "paper-a2"]},
        {"id": cluster_b, "paper_ids": ["paper-b1", "paper-b2"]},
    ]

    plans = plan_review_citations(
        [{"title": "First"}, {"title": "Second"}],
        papers,
        clusters,
        section_reference_target=2,
        core_reference_count=2,
    )

    assert plans[0].key_clusters == [cluster_a]
    assert plans[0].candidate_paper_ids[:2] == ["paper-a1", "paper-a2"]
    assert plans[1].key_clusters == [cluster_b]
    assert plans[1].candidate_paper_ids[:2] == ["paper-b1", "paper-b2"]


def test_explicit_cluster_uses_all_priority_tiers_and_best_hybrid_edge() -> None:
    papers = [{"id": f"paper-{index}"} for index in range(6)]
    clusters = [
        {"id": "cluster-a", "paper_ids": ["paper-0", "paper-3"]},
        {"id": "cluster-b", "paper_ids": ["paper-1", "paper-4"]},
        {"id": "cluster-c", "paper_ids": ["paper-2", "paper-5"]},
    ]
    hybrid_edges = [
        {
            "source_paper_id": "paper-0",
            "target_paper_id": "paper-1",
            "weight": 0.8,
            "rank": 2,
        },
        {
            "source_paper_id": "paper-3",
            "target_paper_id": "paper-1",
            "weight": 0.9,
            "rank": 5,
        },
        {
            "source_paper_id": "paper-5",
            "target_paper_id": "paper-0",
            "weight": 0.7,
            "rank": 1,
        },
        {
            "source_paper_id": "missing",
            "target_paper_id": "paper-0",
            "weight": 1.0,
        },
        {
            "source_paper_id": "paper-0",
            "target_paper_id": "paper-3",
            "weight": 1.0,
        },
    ]

    plan = plan_review_citations(
        [{"title": "Explicit", "target_communities": ["cluster-a"]}],
        papers,
        clusters,
        section_reference_target=6,
        hybrid_edges=hybrid_edges,
        core_reference_count=3,
    )[0]

    assert plan.candidate_paper_ids == [
        "paper-0",
        "paper-3",
        "paper-1",
        "paper-5",
        "paper-2",
        "paper-4",
    ]
    assert [detail["source"] for detail in plan.candidate_details] == [
        "community_core",
        "community_auxiliary",
        "hybrid_neighbor_core",
        "hybrid_neighbor_auxiliary",
        "global_core",
        "global_auxiliary",
    ]
    assert plan.candidate_details[2]["hybrid_anchor_paper_id"] == "paper-3"
    assert plan.candidate_details[2]["hybrid_weight_basis_points"] == 9000
    assert plan.primary_paper_ids == ["paper-0", "paper-1", "paper-2"]
    assert plan.secondary_paper_ids == ["paper-3", "paper-5", "paper-4"]


def test_empty_and_single_section_plans_degrade_deterministically() -> None:
    empty = plan_review_citations(
        [{"title": "No sources", "key_clusters": ["cluster-a"]}],
        [],
        [],
    )[0]

    assert empty.key_clusters == ["cluster-a"]
    assert empty.candidate_paper_ids == []
    assert empty.candidate_details == []

    single = plan_review_citations(
        [{"title": "All clusters"}],
        [{"id": "paper-a"}, {"id": "paper-b"}],
        [
            {"id": "cluster-a", "paper_ids": ["paper-a"]},
            {"id": "cluster-b", "paper_ids": ["paper-b"]},
        ],
        section_reference_target=2,
        core_reference_count=1,
    )[0]

    assert single.key_clusters == []
    assert single.candidate_paper_ids == ["paper-a", "paper-b"]
    assert [detail["source"] for detail in single.candidate_details] == [
        "community_core",
        "community_auxiliary",
    ]
