"""
JSON 修复工具

参考 Rust 版 academic-cluster-rs 的 repair.rs 实现。
当 LLM 返回畸形 JSON 时，尝试自动修复。
"""

import json
from typing import Any

import structlog

logger = structlog.get_logger()


def extract_json_object(text: str) -> str | None:
    """
    从 LLM 响应中提取 JSON 对象（去除 markdown 代码块等包裹）。

    找到第一个 { 到最后一个 } 之间的内容。
    """
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def extract_json_array(text: str) -> str | None:
    """从 LLM 响应中提取 JSON 数组"""
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def strip_markdown_fences(text: str) -> str:
    """去除 markdown 代码块包裹"""
    text = text.strip()
    # ```json ... ``` 或 ``` ... ```
    if text.startswith("```"):
        # 找到第一行结束
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        # 去掉尾部的 ```
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    return text


def try_parse_json(text: str) -> Any | None:
    """
    尝试解析 JSON，支持多种容错策略。

    1. 直接解析
    2. 去除 markdown 代码块后解析
    3. 提取 JSON 对象/数组后解析
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 去除 markdown 代码块
    stripped = strip_markdown_fences(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 策略 3: 提取 JSON 对象
    obj_str = extract_json_object(stripped)
    if obj_str:
        try:
            return json.loads(obj_str)
        except json.JSONDecodeError:
            pass

    # 策略 4: 提取 JSON 数组
    arr_str = extract_json_array(stripped)
    if arr_str:
        try:
            return json.loads(arr_str)
        except json.JSONDecodeError:
            pass

    return None


async def repair_json_with_llm(raw: str, schema_hint: str = "") -> Any | None:
    """
    使用 LLM 修复畸形 JSON。

    Args:
        raw: 畸形的 JSON 字符串
        schema_hint: 可选的 schema 描述，帮助 LLM 理解目标格式

    Returns:
        修复后的 JSON 对象，失败返回 None
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    system_prompt = "You repair malformed JSON. Return strict JSON only. No markdown, no explanations."
    user_prompt = "Repair the following malformed output into one valid JSON object."
    if schema_hint:
        user_prompt += f"\n\nRequired shape:\n{schema_hint}"
    user_prompt += f"\n\nMalformed output:\n{raw}"

    try:
        llm = create_llm(temperature=0.0, max_tokens=4096)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await ainvoke_with_callbacks(llm, messages)

        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        result = try_parse_json(content)
        if result is not None:
            logger.info("JSON repair succeeded via LLM")
        else:
            logger.warning("JSON repair LLM returned unparseable output")
        return result

    except Exception as e:
        logger.warning("JSON repair via LLM failed", error=str(e))
        return None
