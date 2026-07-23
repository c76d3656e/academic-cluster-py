"""Installed CLI entry point starts the supported API deployment."""

from typing import Any

import pytest

from academic_cluster import cli


def test_cli_runs_one_uvicorn_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs)
    )

    cli.main(["--host", "127.0.0.2", "--port", "8123", "--reload"])

    assert captured == {
        "app": "academic_cluster.api.main:app",
        "host": "127.0.0.2",
        "port": 8123,
        "reload": True,
        "workers": 1,
        "log_level": cli.get_settings().log_level.casefold(),
    }


@pytest.mark.parametrize("port", [0, 65536])
def test_cli_rejects_invalid_port(port: int) -> None:
    with pytest.raises(SystemExit, match="--port"):
        cli.main(["--port", str(port)])
