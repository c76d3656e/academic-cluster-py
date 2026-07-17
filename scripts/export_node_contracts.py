"""Export production node contracts plus deterministic Promptfoo acceptance data."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from academic_cluster.agents.agent_graph import (  # noqa: E402
    AgentState,
    _create_agent_graph,
    _route_from_supervisor,
    decide_next_phase,
)
from academic_cluster.agents.node_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    NODE_NAMES,
    NodeAcceptanceFixture,
    export_contract_json_schema,
)
from academic_cluster.agents.node_contracts import (  # noqa: E402
    accept_node_fixture as _accept_runtime_fixture,
)
from academic_cluster.agents.node_contracts import (  # noqa: E402
    build_all_deterministic_fixtures as _build_runtime_fixtures,
)
from academic_cluster.agents.node_contracts import (  # noqa: E402
    export_contract_manifest as _export_runtime_manifest,
)

FIXTURE_VERSION = "1.0.0"
FIXTURE_SCHEMA_ID = (
    "https://academic-cluster.local/schemas/agent-node-acceptance-fixture-v1.json"
)
BUNDLE_SCHEMA_ID = "academic-cluster.agent-node-acceptance-bundle/v1"
PROMPTFOO_VERSION = "0.121.19"
PROMPTFOO_NODE_ENGINE = "^20.20.0 || >=22.22.0"
PSEUDO_NODES = {"__start__", "__end__"}
REQUIRED_SCENARIO_KEYS = {
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


class ContractError(ValueError):
    """Raised when an acceptance scenario drifts from production contracts."""


def _mapping(value: object, *, location: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{location} must be an object")
    return {str(key): item for key, item in value.items()}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Unable to read JSON fixture {path}: {error}") from error
    return _mapping(value, location=str(path))


def _state_with_patch(state: AgentState, patch: object, *, location: str) -> AgentState:
    update = _mapping(patch, location=location)
    return AgentState.model_validate({**state.model_dump(mode="python"), **update})


def _route_after_node(node: str, state: AgentState) -> str:
    if node == "supervisor":
        return _route_from_supervisor(state)
    if node == "finalize":
        return "__end__"
    return decide_next_phase(state)


def _validate_scenario(
    scenario: dict[str, Any],
    runtime_fixture: NodeAcceptanceFixture,
) -> None:
    node = runtime_fixture.node
    if set(scenario) != REQUIRED_SCENARIO_KEYS:
        raise ContractError(f"{node}: acceptance scenario keys are incomplete")
    if scenario["fixture_version"] != FIXTURE_VERSION:
        raise ContractError(f"{node}: unsupported acceptance fixture version")
    if scenario["schema"] != FIXTURE_SCHEMA_ID:
        raise ContractError(f"{node}: unsupported acceptance fixture schema")
    if scenario["node"] != node:
        raise ContractError(f"{node}: scenario node does not match filename")
    if scenario["contract_version"] != runtime_fixture.contract_version:
        raise ContractError(f"{node}: scenario contract version drifted")
    if scenario["expected_variant"] != runtime_fixture.expected_variant:
        raise ContractError(f"{node}: expected output variant drifted")

    context = _mapping(scenario["context"], location=f"{node}.context")
    if context.get("expected_entry") != node:
        raise ContractError(f"{node}: context entry does not match node")
    required_fields = context.get("required_state_fields")
    if not isinstance(required_fields, list) or not required_fields:
        raise ContractError(f"{node}: required_state_fields must be a list")
    before = _mapping(context.get("before"), location=f"{node}.context.before")
    missing = [field for field in required_fields if field not in before]
    if missing:
        raise ContractError(f"{node}: context is missing {missing}")
    state = AgentState.model_validate(before)
    if node != "supervisor" and decide_next_phase(state) != node:
        raise ContractError(f"{node}: context does not route into its node")

    for section_name in ("error", "fallback"):
        section = _mapping(
            scenario[section_name],
            location=f"{node}.{section_name}",
        )
        if not isinstance(section.get("mode"), str) or not section["mode"]:
            raise ContractError(f"{node}.{section_name}: mode is required")
        scenario_state = _state_with_patch(
            state,
            section.get("state_patch"),
            location=f"{node}.{section_name}.state_patch",
        )
        actual_route = _route_after_node(node, scenario_state)
        if actual_route != section.get("expected_route"):
            raise ContractError(
                f"{node}.{section_name}: expected route "
                f"{section.get('expected_route')}, got {actual_route}"
            )

    expected_acceptance = _mapping(
        scenario["acceptance"], location=f"{node}.acceptance"
    )
    if expected_acceptance != {
        "expected_accepted": True,
        "expected_artifact_version": CONTRACT_VERSION,
    }:
        raise ContractError(f"{node}: acceptance expectations drifted")
    result = _accept_runtime_fixture(runtime_fixture)
    if not result.accepted:
        raise ContractError(f"{node}: runtime fixture was rejected: {result.errors}")
    if result.input_artifact is None or result.output_artifact is None:
        raise ContractError(f"{node}: runtime acceptance omitted artifacts")
    if result.input_artifact.version != CONTRACT_VERSION:
        raise ContractError(f"{node}: input Artifact version drifted")
    if result.output_artifact.version != CONTRACT_VERSION:
        raise ContractError(f"{node}: output Artifact version drifted")


def build_all_deterministic_fixtures() -> tuple[NodeAcceptanceFixture, ...]:
    """Expose production deterministic fixtures for CI consumers."""

    return _build_runtime_fixtures()


def export_contract_manifest() -> dict[str, Any]:
    """Expose the production contract manifest without wrapping or rewriting it."""

    return _export_runtime_manifest()


def _load_scenarios(fixtures_dir: Path) -> list[dict[str, Any]]:
    runtime_fixtures = build_all_deterministic_fixtures()
    names = {path.stem for path in fixtures_dir.glob("*.json")}
    if names != set(NODE_NAMES):
        raise ContractError(
            "Scenario fixtures must match production nodes exactly: "
            f"expected {sorted(NODE_NAMES)}, got {sorted(names)}"
        )
    scenarios: list[dict[str, Any]] = []
    for runtime_fixture in runtime_fixtures:
        scenario = _load_json(fixtures_dir / f"{runtime_fixture.node}.json")
        _validate_scenario(scenario, runtime_fixture)
        scenarios.append(scenario)
    return scenarios


def _runtime_graph() -> tuple[list[str], list[dict[str, Any]]]:
    graph = _create_agent_graph().compile().get_graph()
    runtime_nodes = {name for name in graph.nodes if name not in PSEUDO_NODES}
    if runtime_nodes != set(NODE_NAMES):
        raise ContractError("Production graph nodes differ from NodeContract registry")
    edges = sorted(
        (
            {
                "source": edge.source,
                "target": edge.target,
                "conditional": bool(edge.conditional),
            }
            for edge in graph.edges
        ),
        key=lambda item: (
            str(item["source"]),
            str(item["target"]),
            bool(item["conditional"]),
        ),
    )
    return list(NODE_NAMES), edges


def build_contract_bundle(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Combine canonical runtime contracts with Promptfoo routing scenarios."""

    runtime_fixtures = build_all_deterministic_fixtures()
    acceptance_results = [
        _accept_runtime_fixture(fixture).model_dump(mode="json")
        for fixture in runtime_fixtures
    ]
    nodes, edges = _runtime_graph()
    return {
        "fixture_bundle_version": FIXTURE_VERSION,
        "schema": BUNDLE_SCHEMA_ID,
        "promptfoo": {
            "version": PROMPTFOO_VERSION,
            "node_engine": PROMPTFOO_NODE_ENGINE,
            "offline": True,
        },
        "graph": {
            "entry": "supervisor",
            "terminal": "__end__",
            "nodes": nodes,
            "edges": edges,
        },
        "runtime_contract_manifest": export_contract_manifest(),
        "runtime_contract_schema": export_contract_json_schema(),
        "runtime_acceptance_fixtures": [
            fixture.model_dump(mode="json") for fixture in runtime_fixtures
        ],
        "runtime_acceptance_results": acceptance_results,
        "routing_scenarios": _load_scenarios(
            repository_root / "promptfoo" / "fixtures"
        ),
    }


def render_contract_bundle(repository_root: Path = REPOSITORY_ROOT) -> str:
    """Render the canonical, diff-friendly JSON representation."""

    return (
        json.dumps(
            build_contract_bundle(repository_root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _resolve_output(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("promptfoo/contracts/node-contracts.json"),
        help="Output path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the checked-in machine-readable bundle is stale",
    )
    args = parser.parse_args(argv)
    output_path = _resolve_output(args.output)
    rendered = render_contract_bundle()
    if args.check:
        if not output_path.is_file():
            print(f"Missing node contract bundle: {output_path}", file=sys.stderr)
            return 1
        if output_path.read_text(encoding="utf-8") != rendered:
            print(f"Stale node contract bundle: {output_path}", file=sys.stderr)
            return 1
        print(f"Node contract bundle is current: {output_path}")
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Exported node contracts to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
