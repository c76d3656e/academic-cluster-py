from academic_cluster.graphs.graph import should_revise_sections
from academic_cluster.graphs.state import PipelineState


def test_should_revise_sections_routes_low_coverage_to_revision():
    state = PipelineState(
        project_id="project-1",
        query="topic",
        invalid_citation_count=0,
        weighted_coverage_bp=4200,
        weak_citation_support_count=0,
    )

    assert should_revise_sections(state) == "section_revision"


def test_should_revise_sections_routes_weak_support_to_revision():
    state = PipelineState(
        project_id="project-1",
        query="topic",
        invalid_citation_count=0,
        weighted_coverage_bp=9000,
        weak_citation_support_count=6,
    )

    assert should_revise_sections(state) == "section_revision"


def test_should_revise_sections_honors_retry_limit():
    state = PipelineState(
        project_id="project-1",
        query="topic",
        invalid_citation_count=2,
        weighted_coverage_bp=2000,
        weak_citation_support_count=9,
        retry_count=2,
    )

    assert should_revise_sections(state) == "artifact_registration"
