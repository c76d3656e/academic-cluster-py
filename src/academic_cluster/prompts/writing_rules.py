"""
统一写作规则管理

所有 AI 检测、写作风格约束、禁止表达的单一来源。
其他模块应从这里导入，不要重复定义。
"""

# =============================================================================
# AI 高频词
# =============================================================================

AI_WORDS_EN = [
    "delve",
    "crucial",
    "tapestry",
    "paradigm",
    "nuanced",
    "pivotal",
    "intricate",
    "multifaceted",
    "holistic",
    "comprehensive",
    "endeavor",
    "foster",
    "mitigate",
    "leverage",
    "streamline",
    "robust",
    "innovative",
    "cutting-edge",
    "state-of-the-art",
    "groundbreaking",
    "transformative",
    "revolutionary",
    "unprecedented",
    "unparalleled",
    "meticulous",
    "bespoke",
    "myriad",
    "plethora",
]

AI_WORDS_ZH = [
    "深入探讨",
    "值得注意的是",
    "综上所述",
    "总而言之",
    "不容忽视",
    "至关重要",
    "显而易见",
    "不言而喻",
    "作为一种",
    "在当今",
    "具有重要意义",
    "发挥着重要作用",
    "扮演着重要角色",
]


# =============================================================================
# 清喉式开头
# =============================================================================

THROAT_CLEARING_EN = [
    "It is important to note that",
    "It should be noted that",
    "It is worth mentioning",
    "In the realm of",
    "In terms of",
    "With regard to",
    "As a matter of fact",
    "For all intents and purposes",
    "In today's world",
    "It goes without saying",
]

THROAT_CLEARING_ZH = [
    "值得注意的是",
    "需要指出的是",
    "不言而喻",
    "众所周知",
    "事实上",
    "从某种意义上说",
    "作为一种重要的",
    "在当今社会",
    "具有十分重要的意义",
]


# =============================================================================
# 禁止的总结性连接词
# =============================================================================

BANNED_SUMMARY_CONNECTORS = [
    "综上所述",
    "总之",
    "总而言之",
    "综上",
    "概括而言",
    "总的来说",
    "整体而言",
    "由此可见",
]


# =============================================================================
# 禁止的空洞短语（从方法论角度等）
# =============================================================================

BANNED_FILLER_PHRASES_ZH = [
    "从方法论角度",
    "从技术演进角度",
    "从理论角度",
    "从应用角度",
    "从宏观层面",
    "从微观层面",
    "在理论层面",
    "在实践层面",
    "在技术层面",
    "在方法层面",
    "在应用层面",
    "在模型层面",
    "在数据层面",
    "在性能层面",
    "在效率层面",
    "在架构层面",
    "在算法层面",
    "在系统层面",
]


# =============================================================================
# 段落-任务映射（task_type 定义）
# =============================================================================

PARAGRAPH_TASK_TYPES = {
    "context": "研究背景、问题定义、领域概述",
    "gap": "现有不足、研究空白、未解决问题",
    "approach": "方法路线、技术方案、算法设计",
    "result": "实验结果、关键发现、性能数据",
    "comparison": "方法对比、横向比较、优劣分析",
    "mechanism": "机理分析、原理解释、理论推导",
    "implication": "研究意义、应用前景、影响评估",
    "limitation": "局限性、开放问题、未来方向",
}

# 段落 task_type 的推荐序列（按综述章节位置）
TASK_TYPE_SEQUENCES = {
    "intro": ["context", "gap", "approach", "implication"],
    "method": ["approach", "mechanism", "comparison", "result"],
    "result": ["result", "comparison", "mechanism", "implication"],
    "discussion": ["comparison", "implication", "limitation", "gap"],
    "conclusion": ["implication", "limitation", "gap", "context"],
}


# =============================================================================
# 综合策略类型
# =============================================================================

SYNTHESIS_STRATEGIES = {
    "comparative": "对比式——比较不同方法的异同、优劣、适用场景",
    "inductive": "归纳式——从多个研究中提炼共性规律、趋势、共识",
    "evolutionary": "演进式——按时间线或技术发展脉络组织",
    "taxonomic": "分类式——按机制/原理/应用领域分门别类",
}


# =============================================================================
# 辅助函数
# =============================================================================


def get_all_banned_phrases() -> list[str]:
    """获取所有禁止短语（用于 prompt 注入）"""
    return BANNED_FILLER_PHRASES_ZH + BANNED_SUMMARY_CONNECTORS


def format_banned_phrases_for_prompt() -> str:
    """格式化禁止短语列表为 prompt 文本"""
    lines = ["禁止使用的空洞短语："]
    for phrase in BANNED_FILLER_PHRASES_ZH + BANNED_SUMMARY_CONNECTORS:
        lines.append(f"- {phrase}")
    return "\n".join(lines)


def format_task_types_for_prompt() -> str:
    """格式化段落任务类型为 prompt 文本"""
    lines = ["段落任务类型（每段只做一个任务）："]
    for task, desc in PARAGRAPH_TASK_TYPES.items():
        lines.append(f"- {task}: {desc}")
    return "\n".join(lines)


def format_synthesis_strategies_for_prompt() -> str:
    """格式化综合策略为 prompt 文本"""
    lines = ["综合策略（禁止逐篇罗列，必须选择以下策略之一）："]
    for key, desc in SYNTHESIS_STRATEGIES.items():
        lines.append(f"- {key}: {desc}")
    return "\n".join(lines)
