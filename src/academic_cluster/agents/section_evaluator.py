"""
Section Evaluator Agent

评估已写 section 的质量，提供评分和修订反馈。
"""

import math
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ..prompts.writing_rules import (
    AI_WORDS_EN,
    AI_WORDS_ZH,
    THROAT_CLEARING_EN,
    THROAT_CLEARING_ZH,
)
from ..services.llm_client import ainvoke_with_callbacks, create_llm
from ..tools.json_repair import try_parse_json

logger = structlog.get_logger()
DEFAULT_SECTION_EVALUATION_TIMEOUT_S = 180.0

# 评估失败时的默认返回值
_DEFAULT_EVALUATION = {
    "score": 70,
    "dimensions": {
        "coverage": {"score": 70, "comment": "评估解析失败，请人工审查覆盖度"},
        "logic": {"score": 70, "comment": "评估解析失败，请人工审查逻辑链"},
        "citations": {"score": 70, "comment": "评估解析失败，请人工审查引用质量"},
        "transitions": {"score": 70, "comment": "评估解析失败，请人工审查过渡"},
        "style": {"score": 70, "comment": "评估解析失败，请人工审查风格"},
    },
    "revision_instructions": "请重新审视段落结构和引用质量",
    "needs_revision": True,
}

# 维度权重
_DIMENSION_WEIGHTS = {
    "coverage": 0.25,
    "logic": 0.25,
    "citations": 0.20,
    "transitions": 0.15,
    "style": 0.15,
}

# 修订阈值
_REVISION_THRESHOLD = 75

# ─── Blind 评估常量 ──────────────────────────────────────────────────────────

# Blind 评估失败时的默认返回值
_DEFAULT_BLIND_EVALUATION = {
    "score": 70,
    "dimensions": {
        "outline_coherence": {
            "score": 70,
            "comment": "评估解析失败，请人工审查大纲连贯性",
        },
        "reference_adequacy": {
            "score": 70,
            "comment": "评估解析失败，请人工审查引用充分性",
        },
        "task_coverage": {"score": 70, "comment": "评估解析失败，请人工审查任务覆盖度"},
        "scope_completeness": {
            "score": 70,
            "comment": "评估解析失败，请人工审查范围完整性",
        },
    },
}

# Blind 评估维度权重
_BLIND_DIMENSION_WEIGHTS = {
    "outline_coherence": 0.30,
    "reference_adequacy": 0.30,
    "task_coverage": 0.20,
    "scope_completeness": 0.20,
}

# 综合评估权重（blind vs visible）
_BLIND_WEIGHT = 0.3
_VISIBLE_WEIGHT = 0.7


def _load_prompt_template() -> str:
    """加载 section_evaluator.md 中 visible 评估的 prompt 模板"""
    from ..prompts import _load_prompt

    content = _load_prompt("section_evaluator.md")
    # 提取 BLIND_EVALUATION 标记之前的内容（visible 评估模板）
    marker = "<!-- BLIND_EVALUATION -->"
    if marker in content:
        return content.split(marker, 1)[0].rstrip()
    return content


def _load_blind_prompt_template() -> str:
    """加载 section_evaluator.md 中 blind 评估的 prompt 模板"""
    from ..prompts import _load_prompt

    content = _load_prompt("section_evaluator.md")
    marker = "<!-- BLIND_EVALUATION -->"
    if marker in content:
        return content.split(marker, 1)[1].strip()
    return ""


def _extract_text_content(response) -> str:
    """从 LLM 响应中提取纯文本内容"""
    content = response.content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content


def _compute_weighted_score(dimensions: dict, weights: dict | None = None) -> int:
    """
    根据各维度分数和权重计算加权总分。

    Args:
        dimensions: {"coverage": {"score": 80, ...}, ...}
        weights: 维度权重映射，默认使用 _DIMENSION_WEIGHTS

    Returns:
        加权总分 (0-100)
    """
    if weights is None:
        weights = _DIMENSION_WEIGHTS
    total = 0.0
    for dim_name, weight in weights.items():
        dim_data = dimensions.get(dim_name, {})
        dim_score = dim_data.get("score", 70)
        total += dim_score * weight
    return round(total)


def _validate_evaluation(
    result: dict,
    dimension_weights: dict | None = None,
    default_instructions: str = "请重新审视段落结构和引用质量",
) -> dict:
    """
    验证并修正评估结果的结构完整性。

    确保所有维度都存在，分数在有效范围内。

    Args:
        result: LLM 返回的评估结果
        dimension_weights: 维度权重映射，默认使用 _DIMENSION_WEIGHTS
        default_instructions: 缺失修订指令时的默认值
    """
    if dimension_weights is None:
        dimension_weights = _DIMENSION_WEIGHTS

    # 确保 dimensions 存在且完整
    dimensions = result.get("dimensions", {})
    for dim_name in dimension_weights:
        if dim_name not in dimensions:
            dimensions[dim_name] = {"score": 70, "comment": "缺少该维度评估"}
        else:
            # 确保分数在 0-100 范围内
            score = dimensions[dim_name].get("score", 70)
            if not isinstance(score, (int, float)):
                score = 70
            dimensions[dim_name]["score"] = max(0, min(100, int(score)))

    result["dimensions"] = dimensions

    # 重新计算加权总分（确保准确）
    result["score"] = _compute_weighted_score(dimensions, dimension_weights)

    # 确保 needs_revision 基于 score
    result["needs_revision"] = result["score"] < _REVISION_THRESHOLD

    # 确保 revision_instructions 存在
    if "revision_instructions" not in result:
        result["revision_instructions"] = default_instructions

    return result


def _paragraph_plan_text(section_outline: dict) -> str:
    paragraph_plan = section_outline.get("paragraph_plan")
    if paragraph_plan in (None, ""):
        paragraph_plan = section_outline.get("paragraphs", "")

    if not isinstance(paragraph_plan, list):
        return str(paragraph_plan or "")

    plan_lines = []
    for i, para in enumerate(paragraph_plan, 1):
        if not isinstance(para, dict):
            plan_lines.append(f"段落 {i}: {para}")
            continue

        task_type = para.get("task_type", "")
        direction = (
            para.get("direction") or para.get("description") or para.get("goal", "")
        )
        synthesis = para.get("synthesis_instruction", "")
        target_words = para.get("target_words", "")
        key_papers = para.get("key_papers", [])
        key_evidence = para.get("key_evidence", [])

        line = f"段落 {i}"
        if task_type:
            line += f" ({task_type})"
        if target_words:
            line += f", 约 {target_words} 字"
        if direction:
            line += f": {direction}"
        if synthesis:
            line += f"；综合要求: {synthesis}"
        if key_papers:
            line += f"；关键文献: {', '.join(str(p) for p in key_papers)}"
        if key_evidence:
            line += f"；关键证据: {', '.join(str(e) for e in key_evidence)}"
        plan_lines.append(line)

    return "\n".join(plan_lines)


# ─── 写作质量自检（词表来自 prompts.writing_rules） ───────────────────────────


def _check_ai_words(draft: str) -> list[dict]:
    """检测 AI 高频词，返回命中列表。"""
    findings: list[dict] = []
    draft_lower = draft.lower()

    for word in AI_WORDS_EN:
        # 英文按词边界匹配
        pattern = r"\b" + re.escape(word) + r"\b"
        count = len(re.findall(pattern, draft_lower))
        if count > 0:
            findings.append(
                {
                    "word": word,
                    "count": count,
                    "language": "en",
                    "suggestion": f"替换为更具体的学术表述，避免 AI 套话 '{word}'",
                }
            )

    for word in AI_WORDS_ZH:
        count = draft.count(word)
        if count > 0:
            findings.append(
                {
                    "word": word,
                    "count": count,
                    "language": "zh",
                    "suggestion": f"替换为更具体的学术表述，避免 AI 套话 '{word}'",
                }
            )

    return findings


def _check_throat_clearing(draft: str) -> list[dict]:
    """检测清喉式开头，返回命中列表（含大致位置）。"""
    findings: list[dict] = []

    # 按句号/问号/感叹号/换行分句，保留分隔符位置信息
    sentences = re.split(r"(?<=[。！？.!?\n])", draft)
    offset = 0

    for sent in sentences:
        sent_stripped = sent.strip()
        if not sent_stripped:
            offset += len(sent)
            continue

        for phrase in THROAT_CLEARING_EN:
            if sent_stripped.lower().startswith(phrase.lower()):
                findings.append(
                    {
                        "phrase": phrase,
                        "language": "en",
                        "location": f"字符位置 ~{offset}",
                        "context": sent_stripped[:80],
                    }
                )

        for phrase in THROAT_CLEARING_ZH:
            if sent_stripped.startswith(phrase):
                findings.append(
                    {
                        "phrase": phrase,
                        "language": "zh",
                        "location": f"字符位置 ~{offset}",
                        "context": sent_stripped[:80],
                    }
                )

        offset += len(sent)

    return findings


def _split_sentences(draft: str) -> list[str]:
    """按中英文句号/问号/感叹号分句。"""
    parts = re.split(r"[。！？.!?]+", draft)
    return [s.strip() for s in parts if s.strip()]


def _check_burstiness(draft: str) -> dict:
    """
    Burstiness 检测：检查句子长度变化是否过于均匀。

    连续 5+ 句标准差 < 平均字数 15% 时发出警告。
    """
    sentences = _split_sentences(draft)
    if len(sentences) < 5:
        return {
            "sentence_count": len(sentences),
            "avg_length": 0,
            "std_dev": 0,
            "uniform_segments_count": 0,
            "warning": None,
        }

    lengths = [len(s) for s in sentences]
    overall_avg = sum(lengths) / len(lengths)
    overall_std = math.sqrt(sum((x - overall_avg) ** 2 for x in lengths) / len(lengths))

    # 滑动窗口检测连续 5 句过于均匀的段落
    uniform_segments = 0
    window = 5
    for i in range(len(lengths) - window + 1):
        chunk = lengths[i : i + window]
        chunk_avg = sum(chunk) / window
        chunk_std = math.sqrt(sum((x - chunk_avg) ** 2 for x in chunk) / window)
        if chunk_avg > 0 and chunk_std < chunk_avg * 0.15:
            uniform_segments += 1

    warning = None
    if uniform_segments > 0:
        warning = (
            f"检测到 {uniform_segments} 处连续 5+ 句子长度过于均匀"
            f"（平均 {overall_avg:.0f} 字，标准差 {overall_std:.1f}），"
            "建议增加句式长短变化以提升可读性。"
        )

    return {
        "sentence_count": len(sentences),
        "avg_length": round(overall_avg, 1),
        "std_dev": round(overall_std, 1),
        "uniform_segments_count": uniform_segments,
        "warning": warning,
    }


def _check_punctuation(draft: str) -> dict:
    """检测破折号和分号过度使用。"""
    char_count = len(draft)
    if char_count == 0:
        return {
            "dash_count": 0,
            "semicolon_count": 0,
            "per_thousand_dash": 0,
            "per_thousand_semicolon": 0,
            "warnings": [],
        }

    # 中文破折号（——）和英文破折号（--）
    dash_count = draft.count("——") + draft.count("--")
    # 中英文分号
    semicolon_count = draft.count("；") + draft.count(";")

    per_thousand = char_count / 1000.0
    per_thousand_dash = round(dash_count / per_thousand, 2)
    per_thousand_semicolon = round(semicolon_count / per_thousand, 2)

    warnings = []
    if per_thousand_dash > 2:
        warnings.append(
            f"破折号使用过频（每千字 {per_thousand_dash} 个，阈值 2），"
            "建议用逗号或括号替代部分破折号。"
        )
    if per_thousand_semicolon > 2:
        warnings.append(
            f"分号使用过频（每千字 {per_thousand_semicolon} 个，阈值 2），"
            "建议拆分为独立句子或使用逗号。"
        )

    return {
        "dash_count": dash_count,
        "semicolon_count": semicolon_count,
        "per_thousand_dash": per_thousand_dash,
        "per_thousand_semicolon": per_thousand_semicolon,
        "warnings": warnings,
    }


def _check_citation_format(draft: str) -> dict:
    """
    检测引用格式违规：author-year 格式、UUID 引用、meta-commentary、括号化引用说明。
    """
    # Author-year citations: (Author, 2024), (Smith et al., 2023)
    author_year_re = re.compile(
        r"[（(][A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?"
        r"(?:\s*[,;]\s*[A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?)*"
        r"\s*,\s*\d{4}(?:\s*[;,]\s*\d{4})*[）)]"
    )
    author_year_matches = author_year_re.findall(draft)

    # UUID citations: [433802d1-ebf8-49f7-8efc-0183ef0170b8]
    uuid_re = re.compile(
        r"\[[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\]"
    )
    uuid_matches = uuid_re.findall(draft)

    adjacent_numeric_re = re.compile(r"(?:\[[0-9,\s;、，\-–—]+\]){2,}")
    adjacent_numeric_matches = adjacent_numeric_re.findall(draft)

    # Meta-commentary: (字数统计：1520字), (以上为...)
    meta_re = re.compile(
        r"[（(][^）)]*(?:字数统计|总字数|字数达标|以上为|以下为|本节约|共\d+字|约\d+字)[^）)]*[）)]"
    )
    meta_matches = meta_re.findall(draft)

    # Parenthesized citation prose: （文献[24][28]已证实...） or （[27][29]）
    parenthesized_citation_re = re.compile(
        r"[（(]([^（）()]*\[[0-9][0-9,\s;、，\]\[]*\][^（）()]*)[）)]"
    )
    parenthesized_citation_matches = []
    for match in parenthesized_citation_re.finditer(draft):
        inner = match.group(1).strip()
        if re.fullmatch(r"(?:\[[0-9,\s;、，\-–—]+\]\s*)+", inner) or re.search(
            r"[\u4e00-\u9fffA-Za-z]", inner
        ):
            parenthesized_citation_matches.append(match.group(0))

    issues = []
    if author_year_matches:
        issues.append(
            f"author-year引用格式 {len(author_year_matches)} 处: {author_year_matches[:3]}"
        )
    if uuid_matches:
        issues.append(f"UUID引用 {len(uuid_matches)} 处: {uuid_matches[:3]}")
    if adjacent_numeric_matches:
        issues.append(
            f"相邻引用未合并 {len(adjacent_numeric_matches)} 处: {adjacent_numeric_matches[:3]}"
        )
    if meta_matches:
        issues.append(f"meta-commentary {len(meta_matches)} 处: {meta_matches[:3]}")
    if parenthesized_citation_matches:
        issues.append(
            f"括号化引用说明 {len(parenthesized_citation_matches)} 处: "
            f"{parenthesized_citation_matches[:3]}"
        )

    return {
        "author_year_count": len(author_year_matches),
        "uuid_citation_count": len(uuid_matches),
        "adjacent_numeric_citation_count": len(adjacent_numeric_matches),
        "meta_commentary_count": len(meta_matches),
        "parenthesized_citation_count": len(parenthesized_citation_matches),
        "author_year_samples": author_year_matches[:5],
        "uuid_samples": uuid_matches[:5],
        "adjacent_numeric_samples": adjacent_numeric_matches[:5],
        "meta_samples": meta_matches[:5],
        "parenthesized_citation_samples": parenthesized_citation_matches[:5],
        "issues": issues,
    }


def _check_writing_quality(draft: str) -> dict:
    """
    写作质量自检入口：汇总四项检查结果。

    Returns:
        {
            "ai_word_check": [...],
            "throat_clearing_check": [...],
            "burstiness_check": {...},
            "punctuation_check": {...},
            "citation_format_check": {...},
            "severity": "ok" | "warning" | "critical",
            "summary": str,
        }
    """
    ai_words = _check_ai_words(draft)
    throat_clearing = _check_throat_clearing(draft)
    burstiness = _check_burstiness(draft)
    punctuation = _check_punctuation(draft)
    citation_format = _check_citation_format(draft)

    # 判定严重程度
    ai_count = sum(item["count"] for item in ai_words)
    tc_count = len(throat_clearing)
    has_burstiness_warning = burstiness["warning"] is not None
    punctuation_warning_count = len(punctuation["warnings"])
    author_year_count = citation_format["author_year_count"]
    uuid_count = citation_format["uuid_citation_count"]
    adjacent_numeric_count = citation_format["adjacent_numeric_citation_count"]
    meta_count = citation_format["meta_commentary_count"]
    parenthesized_citation_count = citation_format["parenthesized_citation_count"]

    issues = []
    if ai_count > 5:
        issues.append(f"AI高频词 {ai_count} 处")
    if tc_count > 3:
        issues.append(f"清喉式开头 {tc_count} 处")
    if has_burstiness_warning:
        issues.append("句长过于均匀")
    if punctuation_warning_count > 0:
        issues.append(f"标点问题 {punctuation_warning_count} 项")
    if author_year_count > 0:
        issues.append(f"author-year引用格式 {author_year_count} 处")
    if uuid_count > 0:
        issues.append(f"UUID引用 {uuid_count} 处")
    if adjacent_numeric_count > 0:
        issues.append(f"相邻引用未合并 {adjacent_numeric_count} 处")
    if meta_count > 0:
        issues.append(f"meta-commentary {meta_count} 处")
    if parenthesized_citation_count > 0:
        issues.append(f"括号化引用说明 {parenthesized_citation_count} 处")

    # 引用格式问题是 critical（必须修复）
    citation_critical = (
        author_year_count > 0
        or uuid_count > 0
        or adjacent_numeric_count > 0
        or meta_count > 0
        or parenthesized_citation_count > 0
    )

    if ai_count > 10 or tc_count > 5 or citation_critical:
        severity = "critical"
    elif ai_count > 5 or tc_count > 3 or has_burstiness_warning:
        severity = "warning"
    else:
        severity = "ok"

    summary = "；".join(issues) if issues else "写作质量自检通过"

    return {
        "ai_word_check": ai_words,
        "throat_clearing_check": throat_clearing,
        "burstiness_check": burstiness,
        "punctuation_check": punctuation,
        "citation_format_check": citation_format,
        "severity": severity,
        "summary": summary,
    }


async def evaluate_section_blind(
    section_title: str,
    section_outline: dict,
    references: str,
    target_words: int,
    prev_summary: str = "",
    next_outline: dict | None = None,
) -> dict:
    """
    Paper-blind 评估：只看大纲规划和引用列表，不看正文。

    评估维度：
    - outline_coherence (30%): 大纲的逻辑连贯性
    - reference_adequacy (30%): 引用是否充分覆盖关键研究
    - task_coverage (20%): 段落任务分配是否合理
    - scope_completeness (20%): 范围是否完整

    Args:
        section_title: 章节标题
        section_outline: 该 section 的段落规划
        references: 该 section 的引用列表（渲染后的文本）
        target_words: 目标字数
        prev_summary: 前序 section 的摘要
        next_outline: 后序 section 的大纲信息

    Returns:
        {
            "score": int (0-100),
            "dimensions": {dimension: {"score": int, "comment": str}},
        }
    """
    # 提取 section_outline 中的关键字段
    core_question = section_outline.get(
        "core_question", section_outline.get("description", "")
    )
    narrative_arc = section_outline.get("narrative_arc", "")
    paragraph_plan = _paragraph_plan_text(section_outline)

    # 如果 paragraph_plan 是列表，转为可读文本
    if isinstance(paragraph_plan, list):
        plan_lines = []
        for i, para in enumerate(paragraph_plan, 1):
            if isinstance(para, dict):
                desc = para.get("description", para.get("goal", ""))
                key_papers = para.get("key_papers", [])
                line = f"段落 {i}: {desc}"
                if key_papers:
                    line += f" (关键文献: {', '.join(str(p) for p in key_papers)})"
                plan_lines.append(line)
            else:
                plan_lines.append(f"段落 {i}: {para}")
        paragraph_plan = "\n".join(plan_lines)

    # 如果 narrative_arc 是列表，转为文本
    if isinstance(narrative_arc, list):
        narrative_arc = " -> ".join(str(step) for step in narrative_arc)

    # 格式化 next_outline
    next_outline_text = "无"
    if next_outline:
        if isinstance(next_outline, dict):
            next_title = next_outline.get("title", "")
            next_desc = next_outline.get("description", "")
            next_outline_text = (
                f"{next_title}: {next_desc}" if next_desc else next_title
            )
        else:
            next_outline_text = str(next_outline)

    # 加载 blind prompt 模板
    prompt_template = _load_blind_prompt_template()
    if not prompt_template:
        logger.error(
            "blind evaluation prompt template not found in section_evaluator.md"
        )
        return _DEFAULT_BLIND_EVALUATION

    # 构建 prompt
    prompt = prompt_template.format(
        section_title=section_title,
        core_question=core_question,
        narrative_arc=narrative_arc,
        paragraph_plan=paragraph_plan,
        target_words=target_words,
        prev_summary=prev_summary or "无",
        next_outline=next_outline_text,
        references=references or "暂无引用",
    )

    # 创建 LLM（评估需要确定性，使用 temperature=0.0）
    llm = create_llm(temperature=0.0, max_tokens=4096)

    messages = [
        SystemMessage(
            content="你是一个综述大纲评审专家。你只能看到大纲规划和引用列表，不能看到正文。请严格按照要求的 JSON 格式返回评估结果。"
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await ainvoke_with_callbacks(
            llm,
            messages,
            timeout=DEFAULT_SECTION_EVALUATION_TIMEOUT_S,
        )
        raw_content = _extract_text_content(response)
    except Exception as e:
        logger.error("LLM call failed during blind evaluation", error=str(e))
        return _DEFAULT_BLIND_EVALUATION

    # 解析 JSON（带容错）
    result = try_parse_json(raw_content)
    if result is None:
        logger.warning(
            "Failed to parse blind evaluation JSON",
            section_title=section_title,
            raw_preview=raw_content[:300],
        )
        return _DEFAULT_BLIND_EVALUATION

    # 验证并修正结果
    result = _validate_evaluation(result, _BLIND_DIMENSION_WEIGHTS)

    logger.info(
        "Blind evaluation completed",
        section_title=section_title,
        score=result["score"],
    )

    return result


async def evaluate_section_visible(
    section_title: str,
    section_draft: str,
    section_outline: dict,
    target_words: int,
    prev_summary: str,
    next_outline: dict | None,
) -> dict:
    """
    Paper-visible 评估：评估完整正文的写作质量。

    Args:
        section_title: 章节标题
        section_draft: 已写好的 section 正文
        section_outline: 该 section 的段落规划（来自 section_outline_planner）
        target_words: 目标字数
        prev_summary: 前序 section 的摘要
        next_outline: 后序 section 的大纲信息

    Returns:
        {
            "score": int (0-100),
            "dimensions": {dimension: {"score": int, "comment": str}},
            "revision_instructions": str,
            "needs_revision": bool
        }
    """
    # 提取 section_outline 中的关键字段
    core_question = section_outline.get(
        "core_question", section_outline.get("description", "")
    )
    narrative_arc = section_outline.get("narrative_arc", "")
    paragraph_plan = _paragraph_plan_text(section_outline)

    # 如果 paragraph_plan 是列表，转为可读文本
    if isinstance(paragraph_plan, list):
        plan_lines = []
        for i, para in enumerate(paragraph_plan, 1):
            if isinstance(para, dict):
                desc = para.get("description", para.get("goal", ""))
                key_papers = para.get("key_papers", [])
                line = f"段落 {i}: {desc}"
                if key_papers:
                    line += f" (关键文献: {', '.join(str(p) for p in key_papers)})"
                plan_lines.append(line)
            else:
                plan_lines.append(f"段落 {i}: {para}")
        paragraph_plan = "\n".join(plan_lines)

    # 如果 narrative_arc 是列表，转为文本
    if isinstance(narrative_arc, list):
        narrative_arc = " -> ".join(str(step) for step in narrative_arc)

    # 格式化 next_outline
    next_outline_text = "无"
    if next_outline:
        if isinstance(next_outline, dict):
            next_title = next_outline.get("title", "")
            next_desc = next_outline.get("description", "")
            next_outline_text = (
                f"{next_title}: {next_desc}" if next_desc else next_title
            )
        else:
            next_outline_text = str(next_outline)

    # 加载 prompt 模板
    prompt_template = _load_prompt_template()
    if not prompt_template:
        logger.error("section_evaluator.md prompt template not found")
        return _DEFAULT_EVALUATION

    # 构建 prompt
    prompt = prompt_template.format(
        section_title=section_title,
        section_draft=section_draft,
        core_question=core_question,
        narrative_arc=narrative_arc,
        paragraph_plan=paragraph_plan,
        target_words=target_words,
        prev_summary=prev_summary or "无",
        next_outline=next_outline_text,
    )

    # 创建 LLM（评估需要确定性，使用 temperature=0.0）
    llm = create_llm(temperature=0.0, max_tokens=4096)

    messages = [
        SystemMessage(
            content="你是一个严格的学术综述质量评审员。请严格按照要求的 JSON 格式返回评估结果。"
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await ainvoke_with_callbacks(
            llm,
            messages,
            timeout=DEFAULT_SECTION_EVALUATION_TIMEOUT_S,
        )
        raw_content = _extract_text_content(response)
    except Exception as e:
        logger.error("LLM call failed during section evaluation", error=str(e))
        return _DEFAULT_EVALUATION

    # 解析 JSON（带容错）
    result = try_parse_json(raw_content)
    if result is None:
        logger.warning(
            "Failed to parse section evaluation JSON",
            section_title=section_title,
            raw_preview=raw_content[:300],
        )
        return _DEFAULT_EVALUATION

    # 验证并修正结果
    result = _validate_evaluation(result)

    # ─── 写作质量自检 ────────────────────────────────────────────────────────
    writing_quality = _check_writing_quality(section_draft)
    result["writing_quality_report"] = writing_quality

    # 根据写作质量严重程度调整 style 维度分数
    style_dim = result["dimensions"].get("style", {})
    style_score = style_dim.get("score", 70)

    if writing_quality["severity"] == "critical":
        deduction = min(15, style_score - 40)  # 最多扣 15 分，但不低于 40
        style_score = max(40, style_score - deduction)
        style_dim["score"] = style_score
        style_dim["comment"] = (
            style_dim.get("comment", "")
            + f" [写作质量自检严重问题: {writing_quality['summary']}]"
        )
    elif writing_quality["severity"] == "warning":
        deduction = min(8, style_score - 50)  # 最多扣 8 分，但不低于 50
        style_score = max(50, style_score - deduction)
        style_dim["score"] = style_score
        style_dim["comment"] = (
            style_dim.get("comment", "")
            + f" [写作质量自检警告: {writing_quality['summary']}]"
        )

    result["dimensions"]["style"] = style_dim

    # 重新计算总分（style 分数可能已调整）
    result["score"] = _compute_weighted_score(result["dimensions"])

    # 写作质量问题严重时强制要求修订
    if writing_quality["severity"] == "critical":
        result["needs_revision"] = True
        result["revision_instructions"] = (
            result.get("revision_instructions", "")
            + "\n\n【写作质量自检要求】\n"
            + writing_quality["summary"]
        )
    elif writing_quality["severity"] == "warning" and not result["needs_revision"]:
        result["needs_revision"] = True
        result["revision_instructions"] = (
            result.get("revision_instructions", "")
            + "\n\n【写作质量自检建议】\n"
            + writing_quality["summary"]
        )

    logger.info(
        "Visible evaluation completed",
        section_title=section_title,
        score=result["score"],
        needs_revision=result["needs_revision"],
        writing_quality_severity=writing_quality["severity"],
    )

    return result


async def evaluate_section(
    section_title: str,
    section_draft: str,
    section_outline: dict,
    target_words: int,
    prev_summary: str,
    next_outline: dict | None,
    references: str = "",
) -> dict:
    """
    综合评估（Generator-Evaluator 物理隔离）。

    两阶段评估：
    1. Paper-blind 评估：只看大纲和引用，不看正文（权重 0.3）
    2. Paper-visible 评估：看完整正文（权重 0.7）

    最终分数 = blind_score * 0.3 + visible_score * 0.7

    Args:
        section_title: 章节标题
        section_draft: 已写好的 section 正文
        section_outline: 该 section 的段落规划
        target_words: 目标字数
        prev_summary: 前序 section 的摘要
        next_outline: 后序 section 的大纲信息
        references: 该 section 的引用列表（渲染后的文本）

    Returns:
        {
            "score": int (0-100),
            "dimensions": visible 评估的维度详情,
            "blind_evaluation": blind 评估的完整结果,
            "visible_evaluation": visible 评估的完整结果,
            "revision_instructions": str,
            "needs_revision": bool,
            "writing_quality_report": 写作质量自检报告,
        }
    """
    # Phase 1: Paper-blind 评估
    blind_result = await evaluate_section_blind(
        section_title=section_title,
        section_outline=section_outline,
        references=references,
        target_words=target_words,
        prev_summary=prev_summary,
        next_outline=next_outline,
    )

    # Phase 2: Paper-visible 评估
    visible_result = await evaluate_section_visible(
        section_title=section_title,
        section_draft=section_draft,
        section_outline=section_outline,
        target_words=target_words,
        prev_summary=prev_summary,
        next_outline=next_outline,
    )

    # 综合分数
    final_score = round(
        blind_result["score"] * _BLIND_WEIGHT
        + visible_result["score"] * _VISIBLE_WEIGHT
    )

    # 组合结果
    result = {
        "score": final_score,
        "dimensions": visible_result.get("dimensions", {}),
        "blind_evaluation": blind_result,
        "visible_evaluation": visible_result,
        "revision_instructions": visible_result.get("revision_instructions", ""),
        "needs_revision": final_score < _REVISION_THRESHOLD,
    }

    # 保留写作质量报告
    if "writing_quality_report" in visible_result:
        result["writing_quality_report"] = visible_result["writing_quality_report"]

    # 如果 visible 评估因写作质量问题强制修订，保留该标记
    if visible_result.get("needs_revision", False):
        result["needs_revision"] = True

    logger.info(
        "Combined evaluation completed",
        section_title=section_title,
        final_score=final_score,
        blind_score=blind_result["score"],
        visible_score=visible_result["score"],
        needs_revision=result["needs_revision"],
    )

    return result


async def revise_section(
    section_draft: str,
    revision_instructions: str,
    section_outline: dict,
    references: str,
) -> str:
    """
    根据评估反馈修订 section。

    Args:
        section_draft: 原始 section 正文
        revision_instructions: 修订指令（来自 evaluate_section）
        section_outline: 段落规划
        references: 该 section 的参考文献列表

    Returns:
        修订后的 section 正文
    """
    # 提取段落规划信息
    paragraph_plan = _paragraph_plan_text(section_outline)
    if isinstance(paragraph_plan, list):
        plan_lines = []
        for i, para in enumerate(paragraph_plan, 1):
            if isinstance(para, dict):
                desc = para.get("description", para.get("goal", ""))
                key_papers = para.get("key_papers", [])
                line = f"段落 {i}: {desc}"
                if key_papers:
                    line += f" (关键文献: {', '.join(str(p) for p in key_papers)})"
                plan_lines.append(line)
            else:
                plan_lines.append(f"段落 {i}: {para}")
        paragraph_plan = "\n".join(plan_lines)

    core_question = section_outline.get(
        "core_question", section_outline.get("description", "")
    )
    section_title = section_outline.get("title", "")

    prompt = f"""请根据以下评估反馈修订章节内容。

## 章节标题
{section_title}

## 核心问题
{core_question}

## 段落规划
{paragraph_plan}

## 原始章节正文
{section_draft}

## 修订指令
{revision_instructions}

## 可用参考文献
{references}

## 修订要求
1. 严格按照修订指令进行修改
2. 保持学术语言的正式性和严谨性
3. 引用格式保持 [N] 风格，只使用上方列出的参考文献
4. 不要输出章节标题、参考文献列表或元说明
5. 直接输出修订后的完整章节正文
6. 如果原文含有括号化引用说明（如"（文献[24][28]已证实...）"、"（[27][29]）"），必须改写为正文句法中的内联引用
7. 禁止使用"综上所述"、"总之"、"总而言之"等禁用表达
8. 禁止使用"从方法论角度"、"从技术演进角度"等泛化短语
9. 每个段落以实质性的分析判断或研究发现收尾

请输出修订后的完整章节正文："""

    # 创建 LLM（修订需要适度创造性，使用 temperature=0.3）
    llm = create_llm(temperature=0.3, max_tokens=8192)

    messages = [
        SystemMessage(
            content="你是一个学术写作修订专家。请根据评估反馈精确修订章节内容，保持学术严谨性，并把所有引用写入正文句法。"
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await ainvoke_with_callbacks(
            llm,
            messages,
            timeout=DEFAULT_SECTION_EVALUATION_TIMEOUT_S,
        )
        content = _extract_text_content(response)
    except Exception as e:
        logger.error("LLM call failed during section revision", error=str(e))
        # 修订失败时返回原文
        return section_draft

    logger.info(
        "Section revision completed",
        section_title=section_title,
        original_length=len(section_draft),
        revised_length=len(content),
    )

    return content
