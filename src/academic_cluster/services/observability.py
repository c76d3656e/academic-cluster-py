"""
可观测性服务

提供:
1. structlog 全局配置（JSON 渲染 + 结构化 processor chain）
2. LLMCallbackHandler -- 捕获所有 LLM/Embedding/Rerank 调用的 token 用量和性能指标
3. PipelineTracker -- Pipeline 级别的审计追踪器

所有数据库持久化通过 callable 注入，避免循环依赖。
"""

import asyncio
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Optional

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 500) -> str:
    """截断大文本，保留首尾"""
    if not text or len(text) <= max_len:
        return text
    half = max_len // 2
    return f"{text[:half]}...({len(text)} chars)...{text[-half:]}"


def _summarize_output(output: Any, max_len: int = 500) -> dict:
    """生成输出摘要，截断大文本字段"""
    if output is None:
        return {}
    if not isinstance(output, dict):
        return {"type": type(output).__name__, "repr": _truncate(str(output), max_len)}
    summary = {}
    for k, v in output.items():
        if isinstance(v, str) and len(v) > 200:
            summary[k] = f"<str len={len(v)}>"
        elif isinstance(v, list) and len(v) > 20:
            summary[k] = f"<list len={len(v)}>"
        else:
            summary[k] = v
    return summary

# ---------------------------------------------------------------------------
# Context variables -- 在 pipeline 执行期间标识当前 run 和 node
# ---------------------------------------------------------------------------
_current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
_current_node: ContextVar[str | None] = ContextVar("current_node", default=None)
_current_tracker: ContextVar[Optional["PipelineTracker"]] = ContextVar("current_tracker", default=None)
_current_llm_callback: ContextVar[Optional["LLMCallbackHandler"]] = ContextVar("current_llm_callback", default=None)


def setup_structlog(log_level: str = "INFO"):
    """配置 structlog 全局处理器链（应用启动时调用一次）"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ===========================================================================
# TokenUsageTracker -- 单次 Pipeline Run 的 token 用量聚合器
# ===========================================================================


class TokenUsageTracker:
    """单次 Pipeline Run 的 token 用量聚合器（线程安全）"""

    def __init__(self):
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.total_cost: float = 0.0
        self.call_count: int = 0
        self._lock = asyncio.Lock()
        # 按 provider/model 分组统计
        self.by_provider: dict[str, dict] = {}
        # 按 node 分组统计
        self.by_node: dict[str, dict] = {}

    async def record(
        self,
        node_name: str,
        provider_name: str,
        model_name: str,
        call_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        latency_ms: int,
    ):
        async with self._lock:
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.total_tokens += prompt_tokens + completion_tokens
            self.total_cost += cost
            self.call_count += 1

            # 按 provider 聚合
            key = f"{provider_name}/{model_name}"
            if key not in self.by_provider:
                self.by_provider[key] = {
                    "provider": provider_name,
                    "model": model_name,
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                    "total_latency_ms": 0,
                }
            p = self.by_provider[key]
            p["calls"] += 1
            p["prompt_tokens"] += prompt_tokens
            p["completion_tokens"] += completion_tokens
            p["total_tokens"] += prompt_tokens + completion_tokens
            p["cost"] += cost
            p["total_latency_ms"] += latency_ms

            # 按 node 聚合
            if node_name not in self.by_node:
                self.by_node[node_name] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                }
            n = self.by_node[node_name]
            n["calls"] += 1
            n["prompt_tokens"] += prompt_tokens
            n["completion_tokens"] += completion_tokens
            n["total_tokens"] += prompt_tokens + completion_tokens
            n["cost"] += cost

    def summary(self) -> dict:
        """返回完整的 token 用量汇总"""
        return {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "total_llm_calls": self.call_count,
            "by_provider": list(self.by_provider.values()),
            "by_node": dict(self.by_node),
        }


# ===========================================================================
# LLMCallbackHandler -- LangChain 回调处理器
# ===========================================================================


class LLMCallbackHandler(BaseCallbackHandler):
    """
    捕获所有 LangChain LLM 调用的回调处理器。

    自动记录:
    - 每次 LLM/Embedding/Rerank 调用的 token 用量
    - provider 信息（从 ContextVar 或 metadata 获取）
    - 调用耗时
    - 错误信息

    使用方式: 通过 config={"callbacks": [handler]} 传入 LangChain 调用
    """

    def __init__(
        self,
        tracker: TokenUsageTracker,
        db_caller: Optional[Callable] = None,
    ):
        super().__init__()
        self.tracker = tracker
        self.db_caller = db_caller  # async callable(node_name, provider, model, call_type, prompt_tokens, completion_tokens, latency_ms)
        self._start_times: dict[str, float] = {}
        # 捕获主事件循环，用于从线程池调度异步调用
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._start_times[str(run_id)] = time.monotonic()
        structlog.get_logger().info("LLM callback on_llm_start", run_id=str(run_id))

    def on_llm_end(self, response: LLMResult, *, run_id, **kwargs):
        try:
            start_time = self._start_times.pop(str(run_id), None)
            elapsed_ms = int((time.monotonic() - start_time) * 1000) if start_time is not None else 0

            # 提取 token 用量
            usage: dict = {}
            if response.llm_output:
                usage = response.llm_output.get("token_usage", {})

            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            # 从响应 metadata 提取模型信息
            model_name = "unknown"
            provider_name = "unknown"
            if response.llm_output:
                model_name = response.llm_output.get("model_name", "unknown")

            # 从 ContextVar 获取当前 node
            node_name = _current_node.get() or "unknown"

            _cb_logger = structlog.get_logger()
            _cb_logger.info(
                "LLM callback on_llm_end",
                node=node_name,
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                elapsed_ms=elapsed_ms,
                has_db_caller=self.db_caller is not None,
            )

            # 异步记录到 tracker（fire-and-forget for sync callback）
            # 使用 run_coroutine_threadsafe 从线程池安全地调度异步调用
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.tracker.record(
                        node_name=node_name,
                        provider_name=provider_name,
                        model_name=model_name,
                        call_type="llm",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost=0.0,  # cost 在调用方计算
                        latency_ms=elapsed_ms,
                    ),
                    self._loop,
                )
                # DB call records are written by ainvoke_with_callbacks, where
                # provider/model/request metadata are available. The LangChain
                # callback often lacks provider context and would create duplicate
                # "unknown" rows.
        except Exception as e:
            structlog.get_logger().warning("LLM callback on_llm_end error", error=str(e))

    def on_llm_error(self, error, *, run_id, **kwargs):
        start_time = self._start_times.pop(str(run_id), None)
        elapsed_ms = int((time.monotonic() - start_time) * 1000) if start_time is not None else 0
        logger = structlog.get_logger()
        logger.error(
            "llm_call_failed",
            run_id=str(run_id),
            error=str(error),
            elapsed_ms=elapsed_ms,
            node=_current_node.get(),
        )


# ===========================================================================
# PipelineStatusCallback -- 节点启动时实时更新项目状态
# ===========================================================================


class PipelineStatusCallback(BaseCallbackHandler):
    """
    在 LangGraph 节点开始执行时更新项目状态。

    解决 stream_mode="updates" 只在节点完成后才 emit 事件的问题。
    通过 on_chain_start 在节点实际开始前更新状态。
    """

    def __init__(self, project_id: str, db_caller: Callable):
        super().__init__()
        self.project_id = project_id
        self.db_caller = db_caller  # async callable(project_id, status)
        self._last_node = None
        # 捕获主事件循环，用于从线程池调度异步调用
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        """LangGraph 节点开始时调用"""
        try:
            # LangGraph 的 node name 从 serialized.name 或 inputs 的 __name__ 获取
            node_name = serialized.get("name", "") if isinstance(serialized, dict) else ""
            if not node_name:
                # 尝试从 kwargs 获取
                node_name = kwargs.get("name", "")
            if node_name and node_name != self._last_node:
                self._last_node = node_name
                status = f"running:{node_name}"
                structlog.get_logger().info("PipelineStatusCallback: node started", node=node_name)
                # 使用 run_coroutine_threadsafe 从线程池安全地调度异步调用
                if self._loop is not None:
                    asyncio.run_coroutine_threadsafe(
                        self.db_caller(self.project_id, status), self._loop
                    )
        except Exception as e:
            structlog.get_logger().warning("PipelineStatusCallback error", error=str(e))


# ===========================================================================
# PipelineTracker -- Pipeline 级别的审计追踪器
# ===========================================================================


class PipelineTracker:
    """
    Pipeline 级别的审计追踪器。

    每次 Pipeline 执行创建一个实例，追踪所有节点和 LLM 调用。
    所有数据通过 callable 注入持久化到数据库（避免循环依赖）。

    使用方式::

        tracker = PipelineTracker(project_id, topic, config)
        await tracker.start()

        # 在每个 node 中
        await tracker.begin_node("search", "tool", index=0)
        # ... 执行 node ...
        await tracker.end_node("search", "succeeded")

        # 记录 LLM 调用
        call_id = await tracker.begin_llm_call("llm", "gitee", "internlm3-8b-instruct", ...)
        # ... 执行 LLM ...
        await tracker.end_llm_call(call_id, status="success", ...)

        await tracker.finish("succeeded")
    """

    def __init__(
        self,
        project_id: str,
        topic: str = "",
        config: Optional[dict] = None,
    ):
        self.project_id = project_id
        self.topic = topic
        self.config = config or {}
        self.run_id: Optional[str] = None
        self.token_tracker = TokenUsageTracker()
        self._node_ids: dict[str, str] = {}  # node_name -> execution_id
        self._node_starts: dict[str, float] = {}
        self._start_time: float = 0
        self.logger = structlog.get_logger()

    async def start(self, db_create_run: Optional[Callable] = None) -> str:
        """启动 pipeline run 记录"""
        self._start_time = time.monotonic()
        if db_create_run:
            self.run_id = await db_create_run(
                self.project_id, self.topic, self.config
            )
        else:
            self.run_id = str(uuid.uuid4())

        _current_run_id.set(self.run_id)
        self.logger.info(
            "pipeline_run_started",
            run_id=self.run_id,
            topic=self.topic,
        )
        return self.run_id

    async def begin_node(
        self,
        node_name: str,
        node_type: str = "llm",
        index: int = 0,
        db_create_node: Optional[Callable] = None,
    ):
        """开始节点执行"""
        _current_node.set(node_name)
        self._node_starts[node_name] = time.monotonic()

        if db_create_node and self.run_id:
            exec_id = await db_create_node(
                self.run_id, node_name, node_type, index
            )
            self._node_ids[node_name] = exec_id

        self.logger.info(
            "node_started",
            run_id=self.run_id,
            node=node_name,
            index=index,
        )

    async def end_node(
        self,
        node_name: str,
        status: str = "succeeded",
        error_message: Optional[str] = None,
        error_traceback: Optional[str] = None,
        input_summary: Optional[dict] = None,
        output_summary: Optional[dict] = None,
        db_finish_node: Optional[Callable] = None,
    ):
        """结束节点执行"""
        node_start = self._node_starts.pop(node_name, None)
        if node_start is not None:
            elapsed_ms = int((time.monotonic() - node_start) * 1000)
        else:
            elapsed_ms = 0
        exec_id = self._node_ids.get(node_name)

        node_stats = self.token_tracker.by_node.get(node_name, {})

        if db_finish_node and exec_id:
            await db_finish_node(
                exec_id,
                status=status,
                error_message=error_message,
                error_traceback=error_traceback,
                input_summary=input_summary,
                output_summary=output_summary,
                prompt_tokens=node_stats.get("prompt_tokens", 0),
                completion_tokens=node_stats.get("completion_tokens", 0),
                total_tokens=node_stats.get("total_tokens", 0),
                cost=node_stats.get("cost", 0),
                llm_calls_count=node_stats.get("calls", 0),
            )

        self.logger.info(
            "node_finished",
            run_id=self.run_id,
            node=node_name,
            status=status,
            elapsed_ms=elapsed_ms,
            tokens=node_stats.get("total_tokens", 0),
        )

        _current_node.set(None)

    async def begin_llm_call(
        self,
        call_type: str,
        provider_name: str,
        model_name: str,
        api_base_url: str = "",
        api_key_hint: str = "",
        input_preview: str = "",
        request_metadata: Optional[dict] = None,
        db_create_call: Optional[Callable] = None,
    ) -> Optional[str]:
        """记录 LLM 调用开始，返回 call_id"""
        call_id = None
        if db_create_call and self.run_id:
            node_exec_id = self._node_ids.get(_current_node.get() or "")
            call_id = await db_create_call(
                pipeline_run_id=self.run_id,
                node_execution_id=node_exec_id,
                call_type=call_type,
                provider_name=provider_name,
                model_name=model_name,
                api_base_url=api_base_url,
                api_key_hint=api_key_hint,
                input_preview=input_preview[:500] if input_preview else "",
                request_metadata=request_metadata,
            )
        return call_id

    async def end_llm_call(
        self,
        call_id: Optional[str],
        status: str = "success",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        cost: float = 0.0,
        error_message: Optional[str] = None,
        http_status_code: Optional[int] = None,
        output_preview: str = "",
        db_finish_call: Optional[Callable] = None,
    ):
        """记录 LLM 调用完成"""
        node_name = _current_node.get() or "unknown"

        # 更新 token tracker
        await self.token_tracker.record(
            node_name=node_name,
            provider_name="recorded",
            model_name="recorded",
            call_type="llm",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=latency_ms,
        )

        if db_finish_call and call_id:
            await db_finish_call(
                call_id,
                status=status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                cost=cost,
                error_message=error_message,
                http_status_code=http_status_code,
                output_preview=output_preview[:500] if output_preview else "",
            )

        self.logger.info(
            "llm_call_finished",
            run_id=self.run_id,
            node=node_name,
            call_id=call_id,
            status=status,
            tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
        )

    async def finish(
        self,
        status: str = "succeeded",
        error_message: Optional[str] = None,
        db_finish_run: Optional[Callable] = None,
    ) -> dict:
        """完成 pipeline run，返回 token 用量汇总"""
        elapsed = time.monotonic() - self._start_time
        summary = self.token_tracker.summary()

        if db_finish_run and self.run_id:
            await db_finish_run(
                self.run_id,
                status=status,
                error_message=error_message,
                elapsed_seconds=elapsed,
                total_tokens=summary["total_tokens"],
                total_cost=summary["total_cost"],
                llm_calls_count=summary["total_llm_calls"],
            )

        self.logger.info(
            "pipeline_run_finished",
            run_id=self.run_id,
            status=status,
            elapsed_seconds=round(elapsed, 2),
            **summary,
        )

        _current_run_id.set(None)
        _current_node.set(None)

        return summary


# ===========================================================================
# 便捷工厂函数
# ===========================================================================


def create_llm_callback_handler(
    tracker: TokenUsageTracker,
    db_caller: Optional[Callable] = None,
) -> LLMCallbackHandler:
    """创建 LLM 回调处理器实例"""
    return LLMCallbackHandler(tracker=tracker, db_caller=db_caller)


def create_pipeline_tracker(
    project_id: str,
    topic: str = "",
    config: Optional[dict] = None,
) -> PipelineTracker:
    """创建 Pipeline 追踪器实例"""
    return PipelineTracker(project_id=project_id, topic=topic, config=config)


def get_current_run_id() -> Optional[str]:
    """获取当前 pipeline run ID（从 ContextVar）"""
    return _current_run_id.get()


def get_current_node() -> Optional[str]:
    """获取当前正在执行的 node 名称（从 ContextVar）"""
    return _current_node.get()


def get_current_tracker() -> Optional["PipelineTracker"]:
    """获取当前 PipelineTracker 实例（从 ContextVar）"""
    return _current_tracker.get()


def set_current_tracker(tracker: Optional["PipelineTracker"]) -> None:
    """设置当前 PipelineTracker 实例（在 pipeline 启动时调用）"""
    _current_tracker.set(tracker)


def get_current_llm_callback() -> Optional["LLMCallbackHandler"]:
    """获取当前 LLMCallbackHandler 实例（从 ContextVar）"""
    return _current_llm_callback.get()


def set_current_llm_callback(callback: Optional["LLMCallbackHandler"]) -> None:
    """设置当前 LLMCallbackHandler 实例（在 pipeline 启动时调用）"""
    _current_llm_callback.set(callback)
