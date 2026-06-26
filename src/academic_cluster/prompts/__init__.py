"""
写作提示模板模块

参考 Rust 版本的 prompt 设计，提供高质量的学术写作指导。
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def _load_prompt(name: str) -> str:
    """加载提示模板文件"""
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


# === 搜索相关 ===


def get_parse_topic_prompt() -> str:
    """获取主题解析和搜索 query 生成提示"""
    return _load_prompt("parse_topic.md")


def get_refine_query_prompt() -> str:
    """获取基于缺口的 query 补充提示"""
    return _load_prompt("refine_query.md")


def get_evaluate_search_prompt() -> str:
    """获取搜索结果评估提示"""
    return _load_prompt("evaluate_search.md")


def get_cluster_targeted_refine_prompt() -> str:
    """获取聚类定向补充搜索提示"""
    return _load_prompt("cluster_targeted_refine.md")


def get_decide_refinement_prompt() -> str:
    """获取是否需要补充搜索的判断提示"""
    return _load_prompt("decide_refinement.md")


def get_paper_filter_prompt() -> str:
    """获取论文筛选提示"""
    return _load_prompt("paper_filter.md")


# === 写作相关 ===


def get_generate_outline_prompt() -> str:
    """获取大纲生成提示"""
    return _load_prompt("generate_outline.md")


def get_generate_outline_system_prompt() -> str:
    """获取大纲生成 system prompt"""
    return _load_prompt("generate_outline_system.md")


def get_review_structure_prompt() -> str:
    """获取综述结构指南"""
    return _load_prompt("review_structure.md")


def get_review_style_prompt() -> str:
    """获取写作风格规范"""
    return _load_prompt("review_style.md")


def get_write_section_prompt() -> str:
    """获取章节写作提示"""
    return _load_prompt("write_section.md")


def get_write_system_prompt() -> str:
    """获取章节写作 system prompt 模板"""
    return _load_prompt("write_system.md")


def get_assemble_review_prompt() -> str:
    """获取综述拼装提示（过渡语句、统一风格）"""
    return _load_prompt("assemble_review.md")


def get_generate_abstract_prompt() -> str:
    """获取全文后置摘要生成提示"""
    return _load_prompt("generate_abstract.md")


def get_kg_json_repair_prompt() -> str:
    """获取 KG JSON 修复提示"""
    return _load_prompt("kg_json_repair.md")


def get_section_outline_prompt() -> str:
    """获取章节段落级写作规划提示"""
    return _load_prompt("section_outline.md")


def get_section_evaluator_prompt() -> str:
    """获取章节质量评估提示"""
    return _load_prompt("section_evaluator.md")


# === 分析相关 ===


def get_community_memory_prompt() -> str:
    """获取社区记忆综合提示"""
    return _load_prompt("community_memory.md")


def get_gap_analysis_judge_prompt() -> str:
    """获取差距分析 LLM judge 提示"""
    return _load_prompt("gap_analysis_judge.md")


def get_inter_community_conflict_prompt() -> str:
    """获取跨社区冲突分析提示"""
    return _load_prompt("inter_community_conflict.md")


def get_topic_relevance_filter_prompt() -> str:
    """获取 Topic 相关性过滤评估提示"""
    return _load_prompt("topic_relevance_filter.md")


# === 写作规则（统一管理） ===

from .writing_rules import (  # noqa: E402, F401
    AI_WORDS_EN,
    AI_WORDS_ZH,
    BANNED_FILLER_PHRASES_ZH,
    BANNED_SUMMARY_CONNECTORS,
    PARAGRAPH_TASK_TYPES,
    SYNTHESIS_STRATEGIES,
    TASK_TYPE_SEQUENCES,
    THROAT_CLEARING_EN,
    THROAT_CLEARING_ZH,
    format_banned_phrases_for_prompt,
    format_synthesis_strategies_for_prompt,
    format_task_types_for_prompt,
    get_all_banned_phrases,
)
