"""Authenticated API exposure for machine-readable Agent node contracts."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from academic_cluster.agents.node_contracts import NODE_NAMES
from academic_cluster.api.agent_routes import get_agent_contract, get_agent_contracts


async def test_contract_registry_endpoint_exposes_all_versioned_nodes() -> None:
    manifest = await get_agent_contracts(current_user={"id": "user-1"})

    assert manifest["manifest_version"] == "1.0.0"
    assert manifest["contract_version"] == "1.0.0"
    assert [entry["node"] for entry in manifest["nodes"]] == list(NODE_NAMES)
    assert all("input_artifact_schema" in entry for entry in manifest["nodes"])
    assert all("output_artifact_schema" in entry for entry in manifest["nodes"])


async def test_single_contract_endpoint_returns_exact_node_or_404() -> None:
    research = await get_agent_contract(
        "research",
        current_user={"id": "user-1"},
    )

    assert research["node"] == "research"
    assert research["contract"]["version"] == "1.0.0"
    assert research["input_artifact_schema"]["additionalProperties"] is False
    assert research["output_artifact_schema"]["oneOf"]

    with pytest.raises(HTTPException) as captured:
        await get_agent_contract("unknown", current_user={"id": "user-1"})
    assert captured.value.status_code == 404
