"""
Pipeline 审计日志

为节点添加执行审计日志（耗时、成功/失败）。
Checkpoint 由 LangGraph 原生 AsyncPostgresSaver 自动管理。
"""

import time
from functools import wraps
from typing import Callable

import structlog

from ..services.database import get_database

logger = structlog.get_logger()


def with_audit(node_name: str):
    """
    装饰器：为节点添加审计日志

    功能：
    1. 记录节点开始执行
    2. 执行节点逻辑
    3. 成功后：记录审计日志（耗时、状态）
    4. 失败后：记录失败审计日志

    注意：Checkpoint 由 LangGraph 的 AsyncPostgresSaver 自动管理，
    不需要手动保存。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            db = get_database()
            project_id = state.project_id if hasattr(state, 'project_id') else None
            start_time = time.time()

            logger.info(
                "Node execution started",
                node=node_name,
                project_id=project_id,
            )

            try:
                result = await func(state, *args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)

                if project_id:
                    try:
                        await db.save_audit_log({
                            "project_id": project_id,
                            "node_name": node_name,
                            "event_type": "node_completed",
                            "event_data": {
                                "status": result.get("status", "unknown") if isinstance(result, dict) else "unknown",
                                "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                            },
                            "duration_ms": duration_ms,
                        })
                    except Exception as e:
                        logger.warning("Failed to save audit log", error=str(e))

                logger.info(
                    "Node execution completed",
                    node=node_name,
                    project_id=project_id,
                    duration_ms=duration_ms,
                    status=result.get("status", "unknown") if isinstance(result, dict) else "unknown",
                )

                return result

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                if project_id:
                    try:
                        await db.save_audit_log({
                            "project_id": project_id,
                            "node_name": node_name,
                            "event_type": "node_failed",
                            "event_data": {
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                            "duration_ms": duration_ms,
                        })
                    except Exception as audit_error:
                        logger.warning("Failed to save audit log", error=str(audit_error))

                logger.error(
                    "Node execution failed",
                    node=node_name,
                    project_id=project_id,
                    duration_ms=duration_ms,
                    error=str(e),
                )

                raise

        return wrapper
    return decorator
