"""
Pipeline 审计日志

为节点添加执行审计日志（耗时、成功/失败）。
增强版集成 PipelineTracker，捕获完整 traceback，记录输入/输出摘要和 retry 次数。
Checkpoint 由 LangGraph 原生 AsyncPostgresSaver 自动管理。
"""

import time
import traceback
from functools import wraps
from typing import Callable

import structlog

from ..services.database import get_database
from ..services.observability import _summarize_output, get_current_tracker

logger = structlog.get_logger()


def with_audit(node_name: str):
    """
    装饰器：为节点添加审计日志

    功能：
    1. 记录节点开始执行
    2. 执行节点逻辑
    3. 成功后：记录审计日志（耗时、状态、输出摘要）
    4. 失败后：记录失败审计日志（完整 traceback、retry 次数）
    5. 集成 PipelineTracker（从 state 中获取）

    注意：Checkpoint 由 LangGraph 的 AsyncPostgresSaver 自动管理，
    不需要手动保存。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            db = get_database()
            project_id = state.project_id if hasattr(state, 'project_id') else None
            start_time = time.time()

            # 获取 tracker（从 ContextVar）
            tracker = get_current_tracker()
            if tracker and hasattr(tracker, 'begin_node'):
                try:
                    await tracker.begin_node(
                        node_name, "compute",
                        db_create_node=db.create_node_execution,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to begin tracked node execution",
                        node=node_name,
                        project_id=project_id,
                        error=str(e),
                    )

            logger.info(
                "Node execution started",
                node=node_name,
                project_id=project_id,
            )

            try:
                result = await func(state, *args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)

                # 构建输出摘要
                output_summary = {}
                if isinstance(result, dict):
                    output_summary = _summarize_output(result)

                # 获取 retry 次数
                retry_count = state.retry_count if hasattr(state, 'retry_count') else 0

                if project_id:
                    try:
                        await db.save_audit_log({
                            "project_id": project_id,
                            "node_name": node_name,
                            "event_type": "node_completed",
                            "event_data": {
                                "status": result.get("status", "unknown") if isinstance(result, dict) else "unknown",
                                "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                                "output_summary": output_summary,
                                "retry_count": retry_count,
                            },
                            "duration_ms": duration_ms,
                        })
                    except Exception as e:
                        logger.warning("Failed to save audit log", error=str(e))

                # 更新 tracker
                if tracker and hasattr(tracker, 'end_node'):
                    try:
                        await tracker.end_node(
                            node_name,
                            "succeeded",
                            output_summary=result if isinstance(result, dict) else {},
                            db_finish_node=db.finish_node_execution,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to finish tracked node execution",
                            node=node_name,
                            project_id=project_id,
                            error=str(e),
                        )

                # SSE: 推送节点完成事件
                if project_id:
                    try:
                        from ..api.sse import get_sse_manager
                        sse = get_sse_manager()
                        await sse.send_event(project_id, "node_finished", {
                            "node": node_name,
                            "status": "succeeded",
                            "duration_ms": duration_ms,
                        })
                    except Exception as e:
                        logger.warning(
                            "Failed to finish failed tracked node execution",
                            node=node_name,
                            project_id=project_id,
                            error=str(e),
                        )

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
                tb = traceback.format_exc()
                retry_count = state.retry_count if hasattr(state, 'retry_count') else 0

                if project_id:
                    try:
                        await db.save_audit_log({
                            "project_id": project_id,
                            "node_name": node_name,
                            "event_type": "node_failed",
                            "event_data": {
                                "error": str(e),
                                "error_type": type(e).__name__,
                                "traceback": tb,
                                "retry_count": retry_count,
                            },
                            "duration_ms": duration_ms,
                        })
                    except Exception as audit_error:
                        logger.warning("Failed to save audit log", error=str(audit_error))

                # 更新 tracker
                if tracker and hasattr(tracker, 'end_node'):
                    try:
                        await tracker.end_node(
                            node_name,
                            "failed",
                            error_message=str(e),
                            error_traceback=tb,
                            db_finish_node=db.finish_node_execution,
                        )
                    except Exception:
                        pass

                # SSE: 推送节点失败事件
                if project_id:
                    try:
                        from ..api.sse import get_sse_manager
                        sse = get_sse_manager()
                        await sse.send_event(project_id, "node_finished", {
                            "node": node_name,
                            "status": "failed",
                            "error": str(e),
                        })
                    except Exception:
                        pass

                logger.error(
                    "Node execution failed",
                    node=node_name,
                    project_id=project_id,
                    duration_ms=duration_ms,
                    error=str(e),
                    traceback=tb,
                    retry_count=retry_count,
                )

                raise

        return wrapper
    return decorator
