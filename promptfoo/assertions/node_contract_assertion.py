"""Promptfoo assertion for production-backed node acceptance results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

ALLOWED_ROUTES = {
    "research",
    "analysis",
    "writing",
    "peer_review",
    "finalize",
    "__end__",
}
EXPECTED_CRITERION_SUFFIXES = {
    "input.version",
    "input.required",
    "input.types",
    "output.variant",
    "error.policy",
    "fallback.policy",
}


def _mapping(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}


def _fixture(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return _mapping(value)


def _scenario_is_valid(value: object) -> bool:
    scenario = _mapping(value)
    return bool(
        scenario
        and isinstance(scenario.get("mode"), str)
        and scenario["mode"]
        and isinstance(scenario.get("state_patch"), Mapping)
        and scenario.get("expected_route") in ALLOWED_ROUTES
    )


def _artifact_version(acceptance: dict[str, Any], direction: str) -> object:
    artifact = _mapping(acceptance.get(f"{direction}_artifact"))
    return artifact.get("version") if artifact else None


def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Validate fixture/schema/context/error/fallback and runtime acceptance."""

    assertion_context = _mapping(context) or {}
    config = _mapping(assertion_context.get("config")) or {}
    variables = _mapping(assertion_context.get("vars")) or {}
    provider_response = _mapping(assertion_context.get("providerResponse")) or {}
    provider_metadata = _mapping(provider_response.get("metadata")) or {}
    expected_fixture = _fixture(variables.get("fixture")) or {}
    try:
        document = _mapping(json.loads(output))
    except (json.JSONDecodeError, TypeError):
        document = None
    document = document or {}
    expected_node = config.get("expected_node")
    expected_contract_version = config.get("expected_contract_version")

    context_section = _mapping(document.get("context"))
    before = _mapping(context_section.get("before")) if context_section else None
    required_fields = (
        context_section.get("required_state_fields") if context_section else None
    )
    context_valid = bool(
        context_section
        and before
        and document.get("node") == expected_node == variables.get("node")
        and context_section == expected_fixture.get("context")
        and context_section.get("expected_entry") == expected_node
        and isinstance(required_fields, list)
        and required_fields
        and all(isinstance(field, str) and field in before for field in required_fields)
        and provider_metadata.get("node") == expected_node
        and provider_metadata.get("prompt") == expected_node
    )

    acceptance = _mapping(document.get("acceptance")) or {}
    expected_acceptance = _mapping(expected_fixture.get("acceptance")) or {}
    criteria = acceptance.get("evaluated_criteria")
    criterion_suffixes = (
        {str(item).removeprefix(f"{expected_node}.") for item in criteria}
        if isinstance(criteria, list)
        else set()
    )
    output_artifact = _mapping(acceptance.get("output_artifact")) or {}
    acceptance_valid = bool(
        acceptance.get("accepted") is True
        and acceptance.get("errors") == []
        and expected_acceptance.get("expected_accepted") is True
        and criterion_suffixes == EXPECTED_CRITERION_SUFFIXES
        and output_artifact.get("variant")
        == document.get("expected_variant")
        == expected_fixture.get("expected_variant")
    )
    manifest = _mapping(document.get("manifest")) or {}
    expected_artifact_version = expected_acceptance.get("expected_artifact_version")
    version_valid = bool(
        document.get("fixture_version")
        == config.get("expected_fixture_version")
        == expected_fixture.get("fixture_version")
        and document.get("contract_version")
        == expected_contract_version
        == expected_fixture.get("contract_version")
        and manifest.get("manifest_version") == expected_contract_version
        and manifest.get("contract_version") == expected_contract_version
        and _artifact_version(acceptance, "input")
        == expected_artifact_version
        == expected_contract_version
        and _artifact_version(acceptance, "output") == expected_artifact_version
    )
    checks = {
        "contract_version": version_valid,
        "contract_schema": bool(
            document.get("schema")
            == config.get("expected_fixture_schema")
            == expected_fixture.get("schema")
        ),
        "contract_context": context_valid,
        "contract_error": bool(
            document.get("error") == expected_fixture.get("error")
            and _scenario_is_valid(document.get("error"))
        ),
        "contract_fallback": bool(
            document.get("fallback") == expected_fixture.get("fallback")
            and _scenario_is_valid(document.get("fallback"))
        ),
        "contract_acceptance": acceptance_valid,
    }
    passed = all(checks.values())
    failed = [name for name, result in checks.items() if not result]
    return {
        "pass": passed,
        "score": sum(checks.values()) / len(checks),
        "reason": (
            "Production node contract accepted"
            if passed
            else "Invalid node contract sections: " + ", ".join(failed)
        ),
        "named_scores": {name: float(result) for name, result in checks.items()},
    }


def accept_node_fixture(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Named Promptfoo entry point; keep get_assert for default-file compatibility."""

    return get_assert(output, context)
