"""Command-line entry point for the single-worker API service."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from .config import get_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="academic-cluster",
        description="Run the Academic Cluster API and multi-agent workflow.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload source changes during local development.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Start the only supported one-worker ASGI deployment."""

    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    settings = get_settings()
    uvicorn.run(
        "academic_cluster.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
        log_level=settings.log_level.casefold(),
    )


if __name__ == "__main__":
    main()
