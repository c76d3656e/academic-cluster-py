"""KG relations must use IDs actually returned by normalized entity upserts."""

from academic_cluster.tools.agent_tools import _bind_kg_relation_entity_ids


def test_relation_ids_follow_persisted_normalized_entities() -> None:
    existing_source_id = "11111111-1111-1111-1111-111111111111"
    inserted_target_id = "22222222-2222-2222-2222-222222222222"

    bound, unresolved = _bind_kg_relation_entity_ids(
        [
            {
                "source": "  Large Language Model ",
                "target": "Retrieval-Augmented Generation",
                "relation_type": "uses",
            }
        ],
        {
            "large language model": existing_source_id,
            "retrieval augmented generation": inserted_target_id,
        },
    )

    assert unresolved == 0
    assert bound[0]["source_entity_id"] == existing_source_id
    assert bound[0]["target_entity_id"] == inserted_target_id


def test_relation_with_missing_endpoint_is_not_persisted() -> None:
    bound, unresolved = _bind_kg_relation_entity_ids(
        [{"source": "Known", "target": "Missing", "relation_type": "uses"}],
        {"known": "11111111-1111-1111-1111-111111111111"},
    )

    assert bound == []
    assert unresolved == 1
