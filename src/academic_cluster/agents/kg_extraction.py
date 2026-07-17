"""
知识图谱提取 Agent

负责从论文中提取实体和关系，构建知识图谱。
使用 LLM 进行信息提取，支持批量处理和 JSON 修复。

设计参考 Rust 版 academic-cluster-rs 的 kg_extraction 子图。
"""

import asyncio
import json
import re
import uuid
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

logger = structlog.get_logger()


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
_ENTITY_TYPE_MAP.update(
    {
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
    }
)

_RELATION_TYPE_MAP: dict[str, str] = {}
for _canonical in RELATION_TYPES:
    _RELATION_TYPE_MAP[_canonical.lower()] = _canonical
# 常见变体映射
_RELATION_TYPE_MAP.update(
    {
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
    }
)


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


def _is_valid_uuid(value: str) -> bool:
    """检查字符串是否为合法的 UUID 格式"""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


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
    if isinstance(value, (int, float)) and value == value:  # not NaN
        return max(0.0, min(1.0, float(value)))
    return 0.0


# =============================================================================
# JSON 修复
# =============================================================================


def _strip_thinking_tags(text: str) -> str:
    """去除模型推理标签（如 <think>...</think>）

    许多模型（Qwen3、DeepSeek 等）在输出中包含推理过程，
    用 <think> 标签包裹。这些内容不是 JSON 的一部分，必须清除。

    处理方式：
    1. 移除 <think>...</think> 完整标签对及其内容
    2. 如果只有 </think>（开始标签被截断或不完整），也移除
    """
    # 去掉 <think>...</think>（包括内容）
    text = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.DOTALL)
    # 去掉单独的 </think>（没有对应的开始标签）
    text = re.sub(r"</think\s*>", "", text)
    # 去掉单独的 <think>（没有对应的结束标签）
    text = re.sub(r"<think\b[^>]*>", "", text)
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    """从文本中提取 JSON 对象（对齐 Rust 版 extract_json_object）"""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def _strip_markdown_fences(text: str) -> str:
    """去除 markdown 代码块标记"""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return text.strip()


def _fix_illegal_escapes(text: str) -> str:
    """修复 JSON 中的非法转义字符（如 \\U, \\%, \\( 等）"""
    # 保留合法的 JSON 转义: \\, \/, \", \n, \r, \t, \b, \f, \uXXXX
    # 将其他 \\X 替换为 X（去掉反斜杠）
    return re.sub(
        r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})',
        "",
        text,
    )


def fix_json(json_str: str) -> str:
    """修复常见的 JSON 格式问题"""
    # 1. 去除 markdown 代码块标记
    json_str = _strip_markdown_fences(json_str)

    # 2. 尝试从文本中提取 JSON 对象
    extracted = _extract_json_object(json_str)
    if extracted:
        json_str = extracted

    # 3. 修复非法转义字符
    json_str = _fix_illegal_escapes(json_str)

    # 4. 修复尾随逗号
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*]", "]", json_str)

    return json_str


def _require_json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("LLM returned invalid KG payload: JSON object expected")
    return value


def parse_kg_response(response: str) -> dict[str, Any]:
    """
    解析 LLM 的知识图谱提取响应

    支持：
    - 标准 JSON
    - Markdown 代码块中的 JSON
    - 非法转义字符修复
    - 常见格式错误的修复
    - 模型 thinking 标签过滤（如 Qwen 的 <think> 输出）
    """
    # 第零轮：过滤模型 thinking/推理标签
    # 许多模型（如 Qwen3）会在正式输出前生成 <think>...</think> 推理内容
    # 这些内容不是合法 JSON，必须先清除
    response = _strip_thinking_tags(response)

    # 第一轮：尝试直接解析（先提取 JSON 对象，再 raw）
    extracted = _extract_json_object(response)
    if extracted:
        try:
            return _require_json_object(json.loads(extracted, strict=False))
        except json.JSONDecodeError:
            pass

    try:
        return _require_json_object(json.loads(response, strict=False))
    except json.JSONDecodeError:
        pass

    # 第二轮：用 fix_json 修复后重试
    try:
        fixed = fix_json(response)
        return _require_json_object(json.loads(fixed, strict=False))
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse KG response", error=str(e), response=response[:500]
        )
        raise ValueError(
            f"LLM returned invalid JSON for KG extraction: {response[:200]}"
        ) from e


async def _call_llm_with_retry(
    messages: list[Any],
    max_retries: int = 3,
    temperature: float = 0.1,
    timeout: float = 300,
) -> Any:
    """带重试的 LLM 调用，超时 + 指数退避

    重试策略：
    - 最多重试 max_retries 次
    - 指数退避 3s → 6s → 12s
    - 每次重试使用不同的 provider（轮询故障转移）
    """
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    async def _call() -> Any:
        from ..services.llm_client import ainvoke_with_callbacks, create_llm

        llm = create_llm(temperature=temperature, max_tokens=None)
        return await asyncio.wait_for(
            ainvoke_with_callbacks(llm, messages),
            timeout=timeout,
        )

    return await _call()


# =============================================================================
# 提取函数
# =============================================================================


async def extract_kg_from_papers_batch(
    papers: list[dict[str, Any]],
    max_entities_per_paper: int = 12,
    max_relations_per_paper: int = 12,
) -> dict[str, Any]:
    """
    从一批论文提取知识图谱（多篇打包成一个 prompt，对齐 Rust 版）

    Args:
        papers: 论文列表，每个包含 id, title, abstract
        max_entities_per_paper: 每篇论文最大实体数
        max_relations_per_paper: 每篇论文最大关系数

    Returns:
        包含 entities 和 relations 的字典
    """
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

    response = await _call_llm_with_retry(
        messages,
        max_retries=3,
        temperature=0.1,
        timeout=300,
    )

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


# =============================================================================
# 规范化（对齐 Rust 版 normalize.rs）
# =============================================================================


def normalize_kg(
    raw_entities: list[dict[str, Any]],
    raw_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    规范化知识图谱（对齐 Rust 版 normalize_kg）

    - 实体按 normalized_name 去重，保留最高 confidence
    - 关系验证实体存在、去除自环、规范化类型
    - 按 confidence 降序排列
    """
    # === 实体规范化 ===
    entity_map: dict[str, dict[str, Any]] = {}

    for raw in raw_entities:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        key = normalized_name(name)
        if not key:
            continue

        entity_type = canonical_entity_type(
            str(raw.get("entity_type") or raw.get("type") or "")
        )
        confidence = clamp_confidence(raw.get("confidence", 0.5))
        raw_paper_ids = raw.get("paper_ids")
        paper_ids = (
            [str(pid) for pid in raw_paper_ids if pid and _is_valid_uuid(str(pid))]
            if isinstance(raw_paper_ids, list)
            else []
        )
        raw_aliases = raw.get("aliases")
        aliases = (
            [str(alias).strip() for alias in raw_aliases if str(alias).strip()]
            if isinstance(raw_aliases, list)
            else []
        )
        evidence = str(raw.get("evidence") or "").strip() or None

        if key in entity_map:
            existing = entity_map[key]
            if confidence > existing["confidence"]:
                existing["confidence"] = confidence
                existing["entity_type"] = entity_type
                if evidence:
                    existing["evidence"] = evidence
            # 合并 paper_ids
            for pid in paper_ids:
                if pid not in existing["paper_ids"]:
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
                "paper_ids": paper_ids,
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
        source_name = str(raw.get("source") or "").strip()
        target_name = str(raw.get("target") or "").strip()
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
            str(raw.get("relation_type") or raw.get("type") or "")
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

        raw_paper_ids = raw.get("paper_ids")
        paper_ids = (
            [str(pid) for pid in raw_paper_ids if pid and _is_valid_uuid(str(pid))]
            if isinstance(raw_paper_ids, list)
            else []
        )
        confidence = clamp_confidence(raw.get("confidence", 0.5))
        evidence = str(raw.get("evidence") or "").strip() or None

        relations.append(
            {
                "source": source_name,
                "target": target_name,
                "relation_type": rel_type,
                "paper_ids": paper_ids,
                "confidence": confidence,
                "evidence": evidence,
            }
        )

    # 按 confidence 降序排列
    relations.sort(
        key=lambda r: (-float(str(r["confidence"])), str(r["source"]), str(r["target"]))
    )

    return {
        "entities": entities,
        "relations": relations,
        "stats": {
            "entity_count": len(entities),
            "relation_count": len(relations),
            "dropped_relations": dropped_relations,
        },
    }
