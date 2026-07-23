"""Offline acceptance tests for the six Promptfoo node-contract fixtures."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROMPTFOO_ROOT = REPOSITORY_ROOT / "promptfoo"
CONFIG_PATH = PROMPTFOO_ROOT / "promptfooconfig.yaml"
FIXTURE_SCHEMA_ID = (
    "https://academic-cluster.local/schemas/agent-node-acceptance-fixture-v1.json"
)
FIXTURE_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"
NODES = (
    "supervisor",
    "research",
    "analysis",
    "writing",
    "peer_review",
    "finalize",
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture(node: str) -> dict[str, Any]:
    value = json.loads(
        (PROMPTFOO_ROOT / "fixtures" / f"{node}.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _resolve_file_reference(reference: str) -> Path:
    assert reference.startswith("file://")
    relative = reference.removeprefix("file://")
    if ".py:" in relative:
        relative = relative.rsplit(":", 1)[0]
    assert "\\" not in relative
    posix_path = PurePosixPath(relative)
    assert not posix_path.is_absolute()
    return CONFIG_PATH.parent.joinpath(*posix_path.parts)


def _provider_options() -> dict[str, Any]:
    return {
        "config": {
            "fixture_version": FIXTURE_VERSION,
            "fixture_schema_id": FIXTURE_SCHEMA_ID,
        }
    }


def _assertion_context(
    node: str,
    fixture: dict[str, Any],
    provider_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vars": {"node": node, "fixture": fixture},
        "config": {
            "expected_node": node,
            "expected_fixture_version": FIXTURE_VERSION,
            "expected_fixture_schema": FIXTURE_SCHEMA_ID,
            "expected_contract_version": CONTRACT_VERSION,
        },
        "providerResponse": provider_result,
    }


def test_promptfoo_config_has_one_cross_platform_fixture_per_node() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["prompts"] == ["{{node}}"]
    assert len(config["providers"]) == 1
    provider = config["providers"][0]
    assert _resolve_file_reference(provider["id"]).is_file()
    assert provider["config"] == {
        "workers": 1,
        "fixture_version": FIXTURE_VERSION,
        "fixture_schema_id": FIXTURE_SCHEMA_ID,
    }

    tests = config["tests"]
    assert [test["vars"]["node"] for test in tests] == list(NODES)
    for test, node in zip(tests, NODES, strict=True):
        assert test["description"] == f"contract:{node}"
        fixture_path = _resolve_file_reference(test["vars"]["fixture"])
        assert fixture_path == PROMPTFOO_ROOT / "fixtures" / f"{node}.json"
        assert fixture_path.is_file()
        assertion = test["assert"][0]
        assert assertion["type"] == "python"
        assert assertion["value"].endswith(":accept_node_fixture")
        assert _resolve_file_reference(assertion["value"]).is_file()
        assert assertion["config"] == {
            "expected_node": node,
            "expected_fixture_version": FIXTURE_VERSION,
            "expected_fixture_schema": FIXTURE_SCHEMA_ID,
            "expected_contract_version": CONTRACT_VERSION,
        }

    serialized = json.dumps(config).lower()
    assert "api_key" not in serialized
    assert "openai:" not in serialized
    assert "anthropic:" not in serialized


def test_exported_bundle_uses_canonical_runtime_manifest_and_fixtures() -> None:
    exporter = _load_module(
        "node_contract_exporter",
        REPOSITORY_ROOT / "scripts" / "export_node_contracts.py",
    )
    generated = exporter.build_contract_bundle(REPOSITORY_ROOT)
    checked_in = json.loads(
        (PROMPTFOO_ROOT / "contracts" / "node-contracts.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_fixtures = exporter.build_all_deterministic_fixtures()

    assert checked_in == generated
    assert generated["graph"]["nodes"] == list(NODES)
    assert generated["graph"]["entry"] == "supervisor"
    assert generated["graph"]["terminal"] == "__end__"
    assert generated["promptfoo"] == {
        "version": "0.121.19",
        "node_engine": "^20.20.0 || >=22.22.0",
        "offline": True,
    }
    assert generated["runtime_contract_manifest"] == (
        exporter.export_contract_manifest()
    )
    assert generated["runtime_contract_manifest"]["contract_version"] == (
        CONTRACT_VERSION
    )
    assert "NodeContract" in generated["runtime_contract_schema"]["$defs"]
    assert [fixture.node for fixture in runtime_fixtures] == list(NODES)
    assert [
        fixture["node"] for fixture in generated["runtime_acceptance_fixtures"]
    ] == list(NODES)
    assert all(result["accepted"] for result in generated["runtime_acceptance_results"])
    assert all(
        fixture["contract_version"] == CONTRACT_VERSION
        for fixture in generated["routing_scenarios"]
    )

    schema = json.loads(
        (
            PROMPTFOO_ROOT / "contracts" / "node-acceptance-fixture.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == FIXTURE_SCHEMA_ID
    assert set(schema["required"]) == {
        "fixture_version",
        "schema",
        "node",
        "contract_version",
        "expected_variant",
        "context",
        "error",
        "fallback",
        "acceptance",
    }


def test_export_check_is_independent_of_current_working_directory(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "export_node_contracts.py"),
            "--check",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Node contract bundle is current" in completed.stdout


@pytest.mark.parametrize("node", NODES)
def test_provider_returns_runtime_acceptance_and_artifact_versions(node: str) -> None:
    provider = _load_module(
        "node_contract_provider",
        PROMPTFOO_ROOT / "providers" / "node_contract_provider.py",
    )
    assertion = _load_module(
        "node_contract_assertion",
        PROMPTFOO_ROOT / "assertions" / "node_contract_assertion.py",
    )
    fixture = _load_fixture(node)
    provider_result = provider.call_api(
        node,
        _provider_options(),
        {"vars": {"node": node, "fixture": fixture}},
    )

    assert "error" not in provider_result
    document = json.loads(provider_result["output"])
    assert document != fixture
    assert document["contract_version"] == CONTRACT_VERSION
    assert document["expected_variant"] == fixture["expected_variant"]
    assert document["acceptance"]["accepted"] is True
    assert document["acceptance"]["errors"] == []
    assert document["acceptance"]["input_artifact"]["version"] == CONTRACT_VERSION
    assert document["acceptance"]["output_artifact"]["version"] == CONTRACT_VERSION
    assert (
        document["acceptance"]["output_artifact"]["variant"]
        == (fixture["expected_variant"])
    )

    result = assertion.accept_node_fixture(
        provider_result["output"],
        _assertion_context(node, fixture, provider_result),
    )
    assert result["pass"] is True
    assert result["score"] == 1.0
    assert set(result["named_scores"]) == {
        "contract_version",
        "contract_schema",
        "contract_context",
        "contract_error",
        "contract_fallback",
        "contract_acceptance",
    }
    assert set(result["named_scores"].values()) == {1.0}


@pytest.mark.parametrize(
    ("section", "score_name"),
    [
        ("version", "contract_version"),
        ("schema", "contract_schema"),
        ("context", "contract_context"),
        ("error", "contract_error"),
        ("fallback", "contract_fallback"),
        ("acceptance", "contract_acceptance"),
    ],
)
def test_assertion_rejects_each_contract_dimension(
    section: str,
    score_name: str,
) -> None:
    provider = _load_module(
        "node_contract_provider_negative",
        PROMPTFOO_ROOT / "providers" / "node_contract_provider.py",
    )
    assertion = _load_module(
        "node_contract_assertion_negative",
        PROMPTFOO_ROOT / "assertions" / "node_contract_assertion.py",
    )
    fixture = _load_fixture("supervisor")
    provider_result = provider.call_api(
        "supervisor",
        _provider_options(),
        {"vars": {"node": "supervisor", "fixture": fixture}},
    )
    document = copy.deepcopy(json.loads(provider_result["output"]))
    if section == "version":
        document["contract_version"] = "2.0.0"
    elif section == "schema":
        document["schema"] = "invalid-schema"
    elif section == "context":
        document["context"]["expected_entry"] = "analysis"
    elif section in {"error", "fallback"}:
        document[section]["expected_route"] = "invalid-route"
    else:
        document["acceptance"]["accepted"] = False

    result = assertion.get_assert(
        json.dumps(document),
        _assertion_context("supervisor", fixture, provider_result),
    )
    assert result["pass"] is False
    assert result["named_scores"][score_name] == 0.0


def test_provider_rejects_prompt_context_mismatch_without_external_calls() -> None:
    provider = _load_module(
        "node_contract_provider_mismatch",
        PROMPTFOO_ROOT / "providers" / "node_contract_provider.py",
    )
    fixture = _load_fixture("supervisor")

    result = provider.call_api(
        "analysis",
        _provider_options(),
        {"vars": {"node": "supervisor", "fixture": fixture}},
    )

    assert result["output"] == ""
    assert "rendered prompt" in result["error"]
