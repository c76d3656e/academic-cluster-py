"""
CLI 入口
"""


import structlog
from rich.console import Console

from .config import get_settings

logger = structlog.get_logger()
console = Console()


def main():
    """CLI 主入口"""
    console.print("[bold blue]Academic Cluster[/bold blue]")
    console.print("学术论文聚类与综述生成系统")
    console.print()

    settings = get_settings()

    console.print(f"环境: {settings.app_env}")
    console.print(f"调试模式: {settings.app_debug}")
    console.print()

    # TODO: 实现 CLI 命令
    console.print("[yellow]CLI 命令尚未实现[/yellow]")
    console.print("请使用 API 服务: uvicorn academic_cluster.api.main:app")


if __name__ == "__main__":
    main()
