"""Offline Promptfoo provider backed by production node-contract acceptance APIs."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _as_mapping(value: object, *, name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise TypeError(f"{name} must be an object")


def _decode_fixture(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("fixture must contain a JSON object") from error
    return _as_mapping(value, name="fixture")


def _load_runtime_api() -> tuple[Any, Any, Any]:
    """Import production contracts lazily after making the src layout discoverable."""

    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from academic_cluster.agents.node_contracts import (
        accept_node_fixture,
        build_deterministic_fixture,
        export_contract_manifest,
    )

    return build_deterministic_fixture, accept_node_fixture, export_contract_manifest


def call_api(
    prompt: str,
    options: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one production fixture without calling an LLM or external service."""

    try:
        provider_options = _as_mapping(options, name="options")
        provider_config = _as_mapping(
            provider_options.get("config", {}), name="options.config"
        )
        call_context = _as_mapping(context, name="context")
        variables = _as_mapping(call_context.get("vars", {}), name="context.vars")
        scenario_fixture = _decode_fixture(variables.get("fixture"))
        node = str(variables.get("node") or "").strip()
        if not node:
            raise ValueError("context.vars.node is required")
        if prompt.strip() != node:
            raise ValueError("rendered prompt must equal context.vars.node")
        if scenario_fixture.get("node") != node:
            raise ValueError("fixture node does not match context.vars.node")
        if scenario_fixture.get("fixture_version") != provider_config.get(
            "fixture_version"
        ):
            raise ValueError("fixture version does not match provider configuration")
        if scenario_fixture.get("schema") != provider_config.get("fixture_schema_id"):
            raise ValueError("fixture schema does not match provider configuration")

        build_fixture, accept_fixture, export_manifest = _load_runtime_api()
        runtime_fixture = build_fixture(node)
        if scenario_fixture.get("contract_version") != runtime_fixture.contract_version:
            raise ValueError("fixture contract version does not match runtime contract")
        if scenario_fixture.get("expected_variant") != runtime_fixture.expected_variant:
            raise ValueError("fixture expected variant does not match runtime fixture")
        acceptance_result = accept_fixture(runtime_fixture)
        manifest = export_manifest()
        output_document = {
            "fixture_version": scenario_fixture["fixture_version"],
            "schema": scenario_fixture["schema"],
            "node": node,
            "contract_version": runtime_fixture.contract_version,
            "expected_variant": runtime_fixture.expected_variant,
            "context": scenario_fixture["context"],
            "error": scenario_fixture["error"],
            "fallback": scenario_fixture["fallback"],
            "acceptance": acceptance_result.model_dump(mode="json"),
            "manifest": {
                "manifest_version": manifest["manifest_version"],
                "contract_version": manifest["contract_version"],
            },
        }
        output = json.dumps(
            output_document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "output": output,
            "cached": False,
            "metadata": {
                "node": node,
                "prompt": prompt,
                "fixture_version": scenario_fixture["fixture_version"],
                "contract_version": runtime_fixture.contract_version,
                "schema_id": scenario_fixture["schema"],
            },
        }
    except (ImportError, KeyError, TypeError, ValueError) as error:
        return {"output": "", "error": str(error)}
