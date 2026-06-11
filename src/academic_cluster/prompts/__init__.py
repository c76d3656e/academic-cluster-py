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


def get_review_structure_prompt() -> str:
    """获取综述结构指南"""
    return _load_prompt("review_structure.md")


def get_review_style_prompt() -> str:
    """获取写作风格规范"""
    return _load_prompt("review_style.md")


def get_write_section_prompt() -> str:
    """获取章节写作提示"""
    return _load_prompt("write_section.md")
