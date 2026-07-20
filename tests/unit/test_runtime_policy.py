"""Runtime policy registry and validation contracts."""

import pytest

from academic_cluster.services.runtime_policy import (
    config_definitions,
    validate_config_value,
)


def test_runtime_policy_definitions_expose_writing_and_search_controls() -> None:
    definitions = config_definitions()

    assert definitions["writing.default_target_words"]["value"] == "12000"
    assert definitions["writing.minimum_body_tolerance"]["maximum"] == 0.25
    assert definitions["research.results_per_source"]["maximum"] == 100
    assert definitions["rerank.failure_mode"]["options"] == ["passthrough", "fail"]
    assert definitions["provider.request_timeout_seconds"]["value"] == "300"
    assert definitions["embedding.target_dimensions"]["value"] == "1024"
    assert definitions["research.enabled_sources"]["options"] == [
        "semantic_scholar",
        "arxiv",
        "pubmed",
        "crossref",
        "openalex",
    ]


def test_runtime_policy_validation_rejects_out_of_range_and_unknown_sources() -> None:
    definitions = config_definitions()

    assert (
        validate_config_value(definitions["writing.minimum_body_tolerance"], "0.05")
        == "0.05"
    )
    assert (
        validate_config_value(definitions["research.results_per_source"], "100")
        == "100"
    )
    with pytest.raises(ValueError, match="between"):
        validate_config_value(definitions["research.results_per_source"], "101")
    with pytest.raises(ValueError, match="supported search source"):
        validate_config_value(definitions["research.enabled_sources"], '["unknown"]')
    with pytest.raises(ValueError, match="one of"):
        validate_config_value(definitions["rerank.failure_mode"], "ignore")
