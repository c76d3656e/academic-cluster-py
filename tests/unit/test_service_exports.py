"""Public service exports must resolve after dead-code cleanup."""

from academic_cluster import services


def test_service_all_exports_exist() -> None:
    missing = [name for name in services.__all__ if not hasattr(services, name)]

    assert missing == []
