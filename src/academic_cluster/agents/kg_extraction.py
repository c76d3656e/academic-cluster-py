"""
知识图谱提取 Agent

负责从论文中提取实体和关系，构建知识图谱。
使用 LLM 进行信息提取，支持批量处理和 JSON 修复。
"""

import json
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import get_settings

logger = structlog.get_logger()


# =============================================================================
# 提示模板
# =============================================================================

KG_EXTRACTION_SYSTEM_PROMPT = """你是一个学术知识图谱提取专家。你的任务是从学术论文摘要中提取实体和关系。

实体类型（entity_type）：
- ResearchProblem: 研究问题
- Method: 方法、算法、技术
- Dataset: 数据集、基准
- Metric: 评估指标
- Material: 材料、设备
- Concept: 概念、理论
- Domain: 领域、学科

关系类型（relation_type）：
- uses: 使用
- evaluated_on: 在...上评估
- improves: 改进
- applied_to: 应用到
- based_on: 基于
- proposes: 提出
- compares_with: 与...比较

输出格式（严格 JSON）：
{
  "entities": [
    {
      "name": "实体名称",
      "type": "实体类型",
      "normalized_name": "标准化名称（小写、去除修饰词）"
    }
  ],
  "relations": [
    {
      "source": "源实体名称",
      "target": "目标实体名称",
      "type": "关系类型",
      "confidence": 0.9
    }
  ]
}

注意：
1. 实体名称应该简洁明了
2. normalized_name 用于去重，应该统一格式
3. 关系的 confidence 在 0-1 之间
4. 只提取明确的关系，不要推测
5. 确保输出是有效的 JSON
"""


KG_EXTRACTION_BATCH_PROMPT = """请从以下论文摘要中提取知识图谱实体和关系。

论文 {index}/{total}:
标题: {title}
摘要: {abstract}

请以 JSON 格式输出提取结果。
"""


# =============================================================================
# JSON 修复
# =============================================================================

def fix_json(json_str: str) -> str:
    """修复常见的 JSON 格式问题"""
    # 移除 markdown 代码块标记
    json_str = re.sub(r'```json?\s*', '', json_str)
    json_str = re.sub(r'```\s*$', '', json_str)

    # 移除前后空白
    json_str = json_str.strip()

    # 修复常见的引号问题
    # 将单引号替换为双引号（但不影响内容中的单引号）
    # 这是一个简化的修复，实际可能需要更复杂的逻辑

    # 修复尾随逗号
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)

    return json_str


def parse_kg_response(response: str) -> dict:
    """
    解析 LLM 的知识图谱提取响应

    支持：
    - 标准 JSON
    - Markdown 代码块中的 JSON
    - 常见格式错误的修复
    """
    try:
        # 尝试直接解析
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    try:
        # 尝试修复后解析
        fixed = fix_json(response)
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse KG response", error=str(e), response=response[:200])
        return {"entities": [], "relations": []}


# =============================================================================
# Agent 创建
# =============================================================================

def create_kg_extraction_agent(
    model: str | None = None,
    temperature: float = 0.1,
) -> ChatOpenAI:
    """
    创建知识图谱提取 Agent

    Args:
        model: LLM 模型名称
        temperature: 温度参数，信息提取需要较低的随机性

    Returns:
        LLM 实例
    """
    settings = get_settings()

    if model is None:
        model = settings.llm.model

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
    )

    logger.info("KG extraction agent created", model=model)

    return llm


# =============================================================================
# 提取函数
# =============================================================================

async def extract_kg_from_paper(
    title: str,
    abstract: str,
    index: int = 0,
    total: int = 1,
) -> dict:
    """
    从单篇论文提取知识图谱

    Args:
        title: 论文标题
        abstract: 论文摘要
        index: 当前论文索引
        total: 论文总数

    Returns:
        包含实体和关系的字典
    """
    agent = create_kg_extraction_agent()

    prompt = KG_EXTRACTION_BATCH_PROMPT.format(
        index=index + 1,
        total=total,
        title=title,
        abstract=abstract or "无摘要",
    )

    messages = [
        SystemMessage(content=KG_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await agent.ainvoke(messages)

    result = parse_kg_response(response.content)

    logger.debug(
        "KG extraction completed",
        paper_index=index,
        entities=len(result.get("entities", [])),
        relations=len(result.get("relations", [])),
    )

    return result


async def extract_kg_batch(
    papers: list[dict],
    batch_size: int = 16,
) -> dict:
    """
    批量提取知识图谱

    Args:
        papers: 论文列表，每个包含 title 和 abstract
        batch_size: 批次大小

    Returns:
        合并后的实体和关系
    """
    import asyncio

    all_entities = []
    all_relations = []

    total = len(papers)

    # 分批处理
    for batch_start in range(0, total, batch_size):
        batch = papers[batch_start:batch_start + batch_size]

        # 并行处理批次内的论文
        tasks = [
            extract_kg_from_paper(
                title=p.get("title", ""),
                abstract=p.get("abstract", ""),
                index=batch_start + i,
                total=total,
            )
            for i, p in enumerate(batch)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("KG extraction failed", error=str(result))
                continue

            all_entities.extend(result.get("entities", []))
            all_relations.extend(result.get("relations", []))

    # 标准化和去重
    normalized_entities = normalize_entities(all_entities)
    normalized_relations = normalize_relations(all_relations, normalized_entities)

    logger.info(
        "Batch KG extraction completed",
        total_papers=total,
        unique_entities=len(normalized_entities),
        unique_relations=len(normalized_relations),
    )

    return {
        "entities": normalized_entities,
        "relations": normalized_relations,
    }


def normalize_entities(entities: list[dict]) -> list[dict]:
    """
    标准化和去重实体

    - 统一命名格式
    - 合并相同实体
    - 聚合论文引用
    """
    entity_map = {}

    for entity in entities:
        normalized_name = entity.get("normalized_name", "").lower().strip()
        if not normalized_name:
            normalized_name = entity.get("name", "").lower().strip()

        if normalized_name in entity_map:
            # 合并
            existing = entity_map[normalized_name]
            existing["paper_ids"] = list(set(
                existing.get("paper_ids", []) + entity.get("paper_ids", [])
            ))
        else:
            entity_map[normalized_name] = {
                "name": entity.get("name", normalized_name),
                "type": entity.get("type", "Concept"),
                "normalized_name": normalized_name,
                "paper_ids": entity.get("paper_ids", []),
            }

    return list(entity_map.values())


def normalize_relations(
    relations: list[dict],
    entities: list[dict],
) -> list[dict]:
    """
    标准化和去重关系

    - 使用标准化的实体名称
    - 合并相同关系
    """
    entity_names = {e["normalized_name"] for e in entities}
    relation_map = {}

    for relation in relations:
        source = relation.get("source", "").lower().strip()
        target = relation.get("target", "").lower().strip()
        rel_type = relation.get("type", "related_to")

        # 验证实体存在
        if source not in entity_names or target not in entity_names:
            continue

        key = (source, target, rel_type)

        if key in relation_map:
            existing = relation_map[key]
            existing["paper_ids"] = list(set(
                existing.get("paper_ids", []) + relation.get("paper_ids", [])
            ))
            # 取最高的置信度
            existing["confidence"] = max(
                existing.get("confidence", 0),
                relation.get("confidence", 0),
            )
        else:
            relation_map[key] = {
                "source": source,
                "target": target,
                "type": rel_type,
                "confidence": relation.get("confidence", 0.8),
                "paper_ids": relation.get("paper_ids", []),
            }

    return list(relation_map.values())
