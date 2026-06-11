"""
知识图谱提取 Agent

负责从论文中提取实体和关系，构建知识图谱。
使用 LLM 进行信息提取，支持批量处理和 JSON 修复。

设计参考 Rust 版 academic-cluster-rs 的 kg_extraction 子图。
"""

import json
import re
from typing import Callable, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


# =============================================================================
# Token 用量追踪
# =============================================================================

class TokenUsageTracker:
    """累计追踪 LLM token 用量"""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0

    def add(self, usage: dict):
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)
        self.call_count += 1

    def summary(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }


# 全局 tracker，每个 pipeline run 应重置
_token_tracker = TokenUsageTracker()


def get_token_tracker() -> TokenUsageTracker:
    return _token_tracker


def reset_token_tracker():
    global _token_tracker
    _token_tracker = TokenUsageTracker()


# =============================================================================
# Schema 定义（与 Rust 版对齐）
# =============================================================================

ENTITY_TYPES = [
    "ResearchProblem",
    "Method",
    "Dataset",
    "Metric",
    "Material",
    "Concept",
    "Domain",
]

RELATION_TYPES = [
    "uses",
    "evaluated_on",
    "improves",
    "applied_to",
    "based_on",
    "proposes",
    "compares_with",
]


def _build_schema_guide() -> str:
    """构建 schema 指南（对齐 Rust 版 kg_schema_guide）"""
    entity_lines = "\n".join(f"- {t}" for t in ENTITY_TYPES)
    relation_lines = "\n".join(f"- {t}" for t in RELATION_TYPES)
    return f"""Allowed entity types:
{entity_lines}

Entity type meanings:
- ResearchProblem: research task, challenge, objective, application task, or problem statement.
- Method: algorithm, model, approach, framework, workflow, or methodology.
- Dataset: dataset, benchmark, corpus, knowledge base, or evaluation collection.
- Metric: evaluation metric, score, indicator, measurement, or criterion.
- Material: experimental material, sample, software platform, tool, library, instrument, or resource.
- Concept: finding, theory, limitation, observation, principle, mechanism, or abstract construct.
- Domain: application domain, scientific field, region, location, site, study area, or use case.

Allowed relation types:
{relation_lines}

Relation type meanings:
- uses: a method, material, dataset, or concept is used by another entity.
- evaluated_on: a method or task is evaluated on a dataset, benchmark, metric, or material.
- improves: an entity improves performance, quality, coverage, or another entity.
- applied_to: a method or concept is applied to a problem, domain, material, or dataset.
- based_on: an entity is based on, derived from, supported by, or constrained by another entity.
- proposes: a paper, method, or concept introduces/proposes another method, concept, or problem framing.
- compares_with: one method, dataset, metric, concept, or finding is compared with another."""


# =============================================================================
# 提示模板（对齐 Rust 版 kg_extraction.md）
# =============================================================================

SCHEMA_GUIDE = _build_schema_guide()

KG_EXTRACTION_SYSTEM_PROMPT = (
    "You extract academic knowledge graphs for a review pipeline. "
    "Return strict UTF-8 JSON only. No markdown, no code fences, no explanations."
)

KG_EXTRACTION_USER_TEMPLATE = """Extract normalized entities and relations that are useful for literature clustering and review writing.

Schema:
{schema_guide}

Return exactly one JSON object:
{{
  "entities": [
    {{
      "paper_id": "exact paper id",
      "name": "concise canonical entity name",
      "entity_type": "one allowed entity type",
      "aliases": ["optional alias"],
      "evidence": "short phrase from title or abstract",
      "confidence": 0.0
    }}
  ],
  "relations": [
    {{
      "paper_id": "exact paper id",
      "source": "entity name from entities",
      "target": "entity name from entities",
      "relation_type": "one allowed relation type",
      "evidence": "short phrase from title or abstract",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Output only valid JSON. No markdown, no code fences, no explanations.
- Use only the supplied papers. Do not invent paper ids.
- Use field names entity_type and relation_type exactly.
- Each entity name should be short, specific, and reusable across papers.
- Extraction budget per paper: prefer up to {max_entities_per_paper} entities and up to {max_relations_per_paper} relations.
- Do not pad output to satisfy a budget. Include every high-confidence entity or relation that is useful for clustering and review writing.
- evidence must be a short phrase from the paper title or abstract.
- confidence must be a float between 0.0 and 1.0.
- Prefer ResearchProblem for tasks, challenges, objectives, and application tasks.
- Prefer Concept for findings, theories, limitations, observations, and high-level constructs.
- Prefer Domain for application domains, regions, sites, and study areas.

Papers:
{papers}"""

KG_JSON_REPAIR_TEMPLATE = """Repair the malformed knowledge-graph extraction output into one valid JSON object.

Required shape:
{{
  "entities": [
    {{
      "paper_id": "paper id",
      "name": "entity name",
      "entity_type": "ResearchProblem|Method|Dataset|Metric|Material|Concept|Domain",
      "aliases": [],
      "evidence": "short evidence phrase",
      "confidence": 0.0
    }}
  ],
  "relations": [
    {{
      "paper_id": "paper id",
      "source": "entity name",
      "target": "entity name",
      "relation_type": "uses|evaluated_on|improves|applied_to|based_on|proposes|compares_with",
      "evidence": "short evidence phrase",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Return JSON only.
- Preserve the original meaning.
- Drop incomplete objects rather than inventing missing names.
- Do not add markdown or explanations.

Malformed output:
{raw}"""


# =============================================================================
# 类型规范化（对齐 Rust 版 normalize.rs）
# =============================================================================

_ENTITY_TYPE_MAP: dict[str, str] = {}
for _canonical in ENTITY_TYPES:
    _ENTITY_TYPE_MAP[_canonical.lower()] = _canonical
# 常见变体映射
_ENTITY_TYPE_MAP.update({
    "research problem": "ResearchProblem",
    "task": "ResearchProblem",
    "problem": "ResearchProblem",
    "challenge": "ResearchProblem",
    "objective": "ResearchProblem",
    "application task": "ResearchProblem",
    "methodology": "Method",
    "technique": "Method",
    "algorithm": "Method",
    "approach": "Method",
    "framework": "Method",
    "model": "Method",
    "workflow": "Method",
    "benchmark": "Dataset",
    "corpus": "Dataset",
    "knowledge base": "Dataset",
    "kb": "Dataset",
    "collection": "Dataset",
    "measure": "Metric",
    "score": "Metric",
    "indicator": "Metric",
    "criterion": "Metric",
    "substance": "Material",
    "sample": "Material",
    "tool": "Material",
    "library": "Material",
    "framework_sw": "Material",
    "software": "Material",
    "platform": "Material",
    "instrument": "Material",
    "resource": "Material",
    "finding": "Concept",
    "result": "Concept",
    "observation": "Concept",
    "discovery": "Concept",
    "theory": "Concept",
    "principle": "Concept",
    "law": "Concept",
    "limitation": "Concept",
    "limitations": "Concept",
    "shortcoming": "Concept",
    "bottleneck": "Concept",
    "application": "Domain",
    "use case": "Domain",
    "location": "Domain",
    "region": "Domain",
    "site": "Domain",
    "geographic": "Domain",
    "area": "Domain",
    "basin": "Domain",
    "field": "Domain",
})

_RELATION_TYPE_MAP: dict[str, str] = {}
for _canonical in RELATION_TYPES:
    _RELATION_TYPE_MAP[_canonical.lower()] = _canonical
# 常见变体映射
_RELATION_TYPE_MAP.update({
    "uses_method": "uses",
    "used_in": "uses",
    "uses method": "uses",
    "used": "uses",
    "reports_metric": "evaluated_on",
    "tested_on": "evaluated_on",
    "evaluated on": "evaluated_on",
    "evaluates_on": "evaluated_on",
    "evaluates": "evaluated_on",
    "reports metric": "evaluated_on",
    "improves_over": "improves",
    "outperforms": "improves",
    "improves over": "improves",
    "applies_to": "applied_to",
    "applied to": "applied_to",
    "applies to": "applied_to",
    "supports_finding": "based_on",
    "limited_by": "based_on",
    "belongs_to_cluster": "based_on",
    "based on": "based_on",
    "supported_by": "based_on",
    "derived_from": "based_on",
    "introduces": "proposes",
    "presents": "proposes",
    "compared_with": "compares_with",
    "compares with": "compares_with",
    "related_to": "based_on",
})


def canonical_entity_type(raw: str) -> str:
    """规范化实体类型（对齐 Rust 版 canonical_entity_type）"""
    key = raw.strip().lower()
    if key in _ENTITY_TYPE_MAP:
        return _ENTITY_TYPE_MAP[key]
    # 已经是合法类型
    if raw.strip() in ENTITY_TYPES:
        return raw.strip()
    # 未知类型 fallback 到 Concept
    return "Concept"


def canonical_relation_type(raw: str) -> str:
    """规范化关系类型（对齐 Rust 版 canonical_relation_type）"""
    key = raw.strip().lower()
    if key in _RELATION_TYPE_MAP:
        return _RELATION_TYPE_MAP[key]
    # 已经是合法类型
    if raw.strip() in RELATION_TYPES:
        return raw.strip()
    # 未知类型丢弃（返回原始值，由调用方决定是否过滤）
    return raw.strip()


def normalized_name(value: str) -> str:
    """规范化名称（对齐 Rust 版 normalized_name）"""
    # 非字母数字字符替换为空格，转小写，合并空白
    chars = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch.lower())
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def clamp_confidence(value: float) -> float:
    """限制置信度范围（对齐 Rust 版 clamp_confidence）"""
    if isinstance(value, (int, float)) and not (value != value):  # not NaN
        return max(0.0, min(1.0, float(value)))
    return 0.0


# =============================================================================
# JSON 修复
# =============================================================================

def _extract_json_object(text: str) -> str | None:
    """从文本中提取 JSON 对象（对齐 Rust 版 extract_json_object）"""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return None


def fix_json(json_str: str) -> str:
    """修复常见的 JSON 格式问题"""
    # 尝试从 markdown 代码块中提取
    extracted = _extract_json_object(json_str)
    if extracted:
        json_str = extracted
    else:
        # 移除 markdown 代码块标记
        json_str = re.sub(r'```json?\s*', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        json_str = json_str.strip()

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
    # 先尝试提取 JSON 对象
    extracted = _extract_json_object(response)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    try:
        fixed = fix_json(response)
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse KG response", error=str(e), response=response[:500])
        raise ValueError(f"LLM returned invalid JSON for KG extraction: {response[:200]}")


# =============================================================================
# Agent 创建
# =============================================================================

def create_kg_extraction_agent(
    model: str | None = None,
    temperature: float = 0.1,
) -> ChatOpenAI:
    """创建知识图谱提取 Agent"""
    from ..services.llm_client import create_llm

    llm = create_llm(temperature=temperature)
    logger.info("KG extraction agent created")
    return llm


# =============================================================================
# 提取函数
# =============================================================================

async def extract_kg_from_papers_batch(
    papers: list[dict],
    max_entities_per_paper: int = 12,
    max_relations_per_paper: int = 12,
) -> dict:
    """
    从一批论文提取知识图谱（多篇打包成一个 prompt，对齐 Rust 版）

    Args:
        papers: 论文列表，每个包含 id, title, abstract
        max_entities_per_paper: 每篇论文最大实体数
        max_relations_per_paper: 每篇论文最大关系数

    Returns:
        包含 entities 和 relations 的字典
    """
    agent = create_kg_extraction_agent()

    # 构建 papers 文本（对齐 Rust 版 batch_text）
    paper_lines = []
    for p in papers:
        pid = p.get("id", "")
        title = p.get("title", "")
        abstract = p.get("abstract", "") or ""
        paper_lines.append(f"ID: {pid}\nTitle: {title}\nAbstract: {abstract}")
    papers_text = "\n\n".join(paper_lines)

    prompt = KG_EXTRACTION_USER_TEMPLATE.format(
        schema_guide=SCHEMA_GUIDE,
        max_entities_per_paper=max_entities_per_paper,
        max_relations_per_paper=max_relations_per_paper,
        papers=papers_text,
    )

    messages = [
        SystemMessage(content=KG_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await agent.ainvoke(messages)

    # 追踪 token 用量
    usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", {})
    if usage:
        tracker = get_token_tracker()
        tracker.add({
            "prompt_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
            "completion_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        })

    # LLM 响应 content 可能是 list（多模态格式）或 string
    raw_content = response.content
    if isinstance(raw_content, list):
        raw_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        )

    result = parse_kg_response(raw_content)

    logger.debug(
        "KG batch extraction completed",
        paper_count=len(papers),
        entities=len(result.get("entities", [])),
        relations=len(result.get("relations", [])),
    )

    return result


# =============================================================================
# 批量提取（带进度回调）
# =============================================================================

async def extract_kg_batch(
    papers: list[dict],
    batch_size: int = 12,
    progress_callback: Optional[Callable] = None,
    max_entities_per_paper: int = 12,
    max_relations_per_paper: int = 12,
) -> dict:
    """
    批量提取知识图谱

    每 batch_size 篇论文打包成一个 prompt 发给 LLM（对齐 Rust 版设计）。

    Args:
        papers: 论文列表，每个包含 id, title, abstract
        batch_size: 每个 prompt 包含的论文数
        progress_callback: 进度回调函数，签名 async (current, total, message)
        max_entities_per_paper: 每篇论文最大实体数
        max_relations_per_paper: 每篇论文最大关系数

    Returns:
        规范化后的实体和关系
    """
    import asyncio

    # 重置 token tracker
    reset_token_tracker()

    all_entities = []
    all_relations = []
    total = len(papers)

    # 分批处理
    for batch_start in range(0, total, batch_size):
        batch = papers[batch_start:batch_start + batch_size]
        batch_end = min(batch_start + batch_size, total)

        if progress_callback:
            await progress_callback(
                batch_start,
                total,
                f"KG extraction: papers {batch_start+1}-{batch_end}/{total}",
            )

        try:
            result = await extract_kg_from_papers_batch(
                batch,
                max_entities_per_paper=max_entities_per_paper,
                max_relations_per_paper=max_relations_per_paper,
            )
            raw_entities = result.get("entities", [])
            raw_relations = result.get("relations", [])

            # 设置 paper_ids（从 paper_id 字段提取）
            for entity in raw_entities:
                pid = entity.get("paper_id", "")
                entity["paper_ids"] = [pid] if pid else []

            for rel in raw_relations:
                pid = rel.get("paper_id", "")
                rel["paper_ids"] = [pid] if pid else []

            all_entities.extend(raw_entities)
            all_relations.extend(raw_relations)

        except Exception as e:
            logger.error("KG batch extraction failed", batch_start=batch_start, error=str(e))

        if progress_callback:
            await progress_callback(
                batch_end,
                total,
                f"KG extraction: {batch_end}/{total} papers done",
            )

    # 规范化和去重（对齐 Rust 版 normalize_kg）
    normalized = normalize_kg(all_entities, all_relations)

    tracker = get_token_tracker()
    usage = tracker.summary()

    logger.info(
        "Batch KG extraction completed",
        total_papers=total,
        unique_entities=normalized["stats"]["entity_count"],
        unique_relations=normalized["stats"]["relation_count"],
        dropped_relations=normalized["stats"]["dropped_relations"],
        token_usage=usage,
    )

    return {
        "entities": normalized["entities"],
        "relations": normalized["relations"],
        "token_usage": usage,
    }


# =============================================================================
# 规范化（对齐 Rust 版 normalize.rs）
# =============================================================================

def normalize_kg(
    raw_entities: list[dict],
    raw_relations: list[dict],
) -> dict:
    """
    规范化知识图谱（对齐 Rust 版 normalize_kg）

    - 实体按 normalized_name 去重，保留最高 confidence
    - 关系验证实体存在、去除自环、规范化类型
    - 按 confidence 降序排列
    """
    # === 实体规范化 ===
    entity_map: dict[str, dict] = {}

    for raw in raw_entities:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        key = normalized_name(name)
        if not key:
            continue

        entity_type = canonical_entity_type(raw.get("entity_type") or raw.get("type") or "")
        confidence = clamp_confidence(raw.get("confidence", 0.5))
        paper_ids = raw.get("paper_ids", [])
        aliases = [a.strip() for a in raw.get("aliases", []) if a.strip()]
        evidence = (raw.get("evidence") or "").strip() or None

        if key in entity_map:
            existing = entity_map[key]
            if confidence > existing["confidence"]:
                existing["confidence"] = confidence
                existing["entity_type"] = entity_type
                if evidence:
                    existing["evidence"] = evidence
            # 合并 paper_ids
            for pid in paper_ids:
                if pid and pid not in existing["paper_ids"]:
                    existing["paper_ids"].append(pid)
            # 合并 aliases
            for alias in aliases:
                if alias not in existing["aliases"]:
                    existing["aliases"].append(alias)
        else:
            entity_map[key] = {
                "name": name,
                "entity_type": entity_type,
                "normalized_name": key,
                "paper_ids": [pid for pid in paper_ids if pid],
                "aliases": aliases,
                "confidence": confidence,
                "evidence": evidence,
            }

    # 按 confidence 降序排列
    entities = sorted(
        entity_map.values(),
        key=lambda e: (-e["confidence"], e["name"]),
    )

    # === 关系规范化 ===
    entity_name_set = {e["normalized_name"] for e in entities}
    relation_keys: set[str] = set()
    relations = []
    dropped_relations = 0

    for raw in raw_relations:
        source_name = (raw.get("source") or "").strip()
        target_name = (raw.get("target") or "").strip()
        if not source_name or not target_name:
            dropped_relations += 1
            continue

        source_key = normalized_name(source_name)
        target_key = normalized_name(target_name)

        # 验证实体存在
        if source_key not in entity_name_set:
            dropped_relations += 1
            continue
        if target_key not in entity_name_set:
            dropped_relations += 1
            continue

        # 去除自环
        if source_key == target_key:
            dropped_relations += 1
            continue

        # 规范化关系类型
        rel_type = canonical_relation_type(
            raw.get("relation_type") or raw.get("type") or ""
        )
        # 丢弃未知关系类型
        if rel_type not in RELATION_TYPES:
            dropped_relations += 1
            continue

        # 去重
        key = f"{source_key}\x1f{target_key}\x1f{rel_type}"
        if key in relation_keys:
            continue
        relation_keys.add(key)

        paper_ids = raw.get("paper_ids", [])
        confidence = clamp_confidence(raw.get("confidence", 0.5))
        evidence = (raw.get("evidence") or "").strip() or None

        relations.append({
            "source": source_name,
            "target": target_name,
            "relation_type": rel_type,
            "paper_ids": [pid for pid in paper_ids if pid],
            "confidence": confidence,
            "evidence": evidence,
        })

    # 按 confidence 降序排列
    relations.sort(key=lambda r: (-r["confidence"], r["source"], r["target"]))

    return {
        "entities": entities,
        "relations": relations,
        "stats": {
            "entity_count": len(entities),
            "relation_count": len(relations),
            "dropped_relations": dropped_relations,
        },
    }
