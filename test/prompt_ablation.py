"""
多任务 Prompt 消融实验
======================
覆盖 4 个核心任务，每个任务对比 4 种 prompt 变体：
  1. topic_relevance_filter — 论文相关性评分
  2. write_review (section_writing) — 综述章节写作
  3. kg_extraction — 知识图谱实体/关系提取
  4. evidence_card — 证据卡片生成

Prompt 变体（同结构跨任务）：
  A) 纯基础 prompt   — 无结构、无打分标准、无 few-shot
  B) 仅 Few-shot     — 基础 prompt + 精选样例
  C) 仅优化 prompt   — 当前项目中的优化 prompt（角色+维度+规则+格式）
  D) 完整版          — 优化 prompt + few-shot 叠加

API: Gitee AI (https://ai.gitee.com/v1)
模型: qwen3-8b  框架: litellm  环境: uv
"""
import json
import csv
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from litellm import completion

# ======================== 配置 ========================
API_BASE = "https://ai.gitee.com/v1"
API_KEY = os.environ.get("GITEE_AI_API_KEY")
if not API_KEY:
    raise RuntimeError("GITEE_AI_API_KEY is required")
MODEL = "qwen3-8b"
MAX_WORKERS = 12

OUT_DIR = os.path.dirname(__file__)
OUTPUT_CSV = os.path.join(OUT_DIR, "prompt_ablation.csv")
OUTPUT_JSON = os.path.join(OUT_DIR, "prompt_ablation.json")
OUTPUT_SUMMARY = os.path.join(OUT_DIR, "prompt_ablation_summary.csv")


# ======================== LLM 调用 ========================
def call_llm(system: str, user: str, retries: int = 3) -> dict:
    messages = []
    if system.strip():
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    for attempt in range(retries):
        start = time.time()
        try:
            resp = completion(
                model=f"openai/{MODEL}",
                messages=messages,
                api_base=API_BASE,
                api_key=API_KEY,
                timeout=180,
            )
            elapsed = int((time.time() - start) * 1000)
            usage = resp.usage
            return {
                "content": resp.choices[0].message.content,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "latency_ms": elapsed,
                "error": None,
            }
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return {
                    "content": "",
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "latency_ms": int((time.time() - start) * 1000),
                    "error": str(e)[:300],
                }


# ============================================================
# 任务 1: Topic Relevance Filter
# ============================================================
TOPIC_TEST_CASES = [
    {
        "id": "T01", "topic": "深度学习在医学影像诊断中的应用",
        "title": "A Survey of Deep Learning for Medical Image Analysis",
        "abstract": "This paper provides a comprehensive review of deep learning techniques applied to medical image analysis, including CNN, Transformer, and hybrid architectures for disease detection, segmentation, and classification tasks.",
        "ground_truth": 0.95, "category": "直接相关",
    },
    {
        "id": "T02", "topic": "深度学习在医学影像诊断中的应用",
        "title": "ImageNet Classification with Deep Convolutional Neural Networks",
        "abstract": "We trained a large, deep convolutional neural network to classify the 1.2 million high-resolution images in the ImageNet LSVRC-2010 contest into 1000 different classes.",
        "ground_truth": 0.45, "category": "间接相关（方法基础）",
    },
    {
        "id": "T03", "topic": "深度学习在医学影像诊断中的应用",
        "title": "Deep Learning for Natural Language Processing: A Comprehensive Survey",
        "abstract": "This survey covers deep neural networks applied to various NLP tasks, including machine translation, question answering, sentiment analysis, and text generation.",
        "ground_truth": 0.15, "category": "弱相关（领域不同）",
    },
    {
        "id": "T04", "topic": "深度学习在医学影像诊断中的应用",
        "title": "Attention Is All You Need",
        "abstract": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        "ground_truth": 0.40, "category": "间接相关（方法基础）",
    },
    {
        "id": "T05", "topic": "深度学习在医学影像诊断中的应用",
        "title": "Autonomous Driving Perception with Multi-Sensor Fusion",
        "abstract": "This paper presents a multi-modal fusion framework for 3D object detection in autonomous driving, combining LiDAR, camera, and radar through a transformer-based fusion module.",
        "ground_truth": 0.10, "category": "弱相关（领域不同）",
    },
    {
        "id": "T06", "topic": "磷酸盐尾矿资源化利用技术研究进展",
        "title": "Phosphate recovery from wastewater using calcium silicate hydrate",
        "abstract": "This study investigates phosphate recovery from wastewater using CSH as seeding material. Results show 95% recovery efficiency at pH 8.5.",
        "ground_truth": 0.70, "category": "间接相关（主题近似但对象不同）",
    },
    {
        "id": "T07", "topic": "磷酸盐尾矿资源化利用技术研究进展",
        "title": "磷酸盐尾矿中磷的高效浸出与回收工艺优化",
        "abstract": "本研究针对磷石膏尾矿中磷酸盐的赋存形态，系统评估了酸浸、碱浸和生物浸出三种方法的磷回收效率。结果表明两阶段酸浸-沉淀法可使磷回收率达98%以上，产物纯度97.9%。",
        "ground_truth": 0.98, "category": "直接相关",
    },
    {
        "id": "T08", "topic": "磷酸盐尾矿资源化利用技术研究进展",
        "title": "基于神经网络的锂离子电池剩余寿命预测",
        "abstract": "提出一种融合注意力机制和LSTM的锂离子电池RUL预测方法。在NASA和CALCE电池数据集上实验表明该方法优于现有方法。",
        "ground_truth": 0.05, "category": "弱相关（术语同，领域不同）",
    },
]

TOPIC_FEW_SHOT = [
    {
        "title": "Deep Learning for Chest X-ray Analysis: A Survey",
        "abstract": "This survey examines 156 studies applying deep learning to chest X-ray interpretation, covering pneumonia detection, tuberculosis screening, and lung nodule classification.",
        "relevance_score": 0.95,
        "reason": "直接研究深度学习在胸腔X光影像分析中的应用，与'深度学习在医学影像诊断中的应用'主题100%契合",
    },
    {
        "title": "Deep Residual Learning for Image Recognition",
        "abstract": "We present a residual learning framework to ease training of very deep networks. Evaluated on ImageNet and CIFAR-10. Depth is of central importance for visual recognition.",
        "relevance_score": 0.50,
        "reason": "ResNet是医学影像分析的通用基础架构，但本文不涉及医学影像。方法论有支撑作用，研究问题间接相关",
    },
    {
        "title": "Neural Machine Translation by Jointly Learning to Align and Translate",
        "abstract": "We introduce an attention mechanism for neural machine translation. Applied to English-French translation, achieving state-of-the-art BLEU scores.",
        "relevance_score": 0.10,
        "reason": "研究机器翻译领域，与医学影像完全无关。虽然提出了注意力机制，但应用领域和核心研究问题均不匹配",
    },
]


def _topic_basic(tc: dict) -> tuple[str, str]:
    """A: 纯基础 — 无结构、无打分标准"""
    system = "你是学术文献相关性评估专家。"
    user = (
        f"请判断以下论文与研究主题的相关性，给出 0-1 之间的分数。\n\n"
        f"研究主题：{tc['topic']}\n\n"
        f"论文标题：{tc['title']}\n"
        f"论文摘要：{tc['abstract']}\n\n"
        f"返回格式：JSON {{\"relevance_score\": 0.XX, \"reason\": \"...\"}}"
    )
    return system, user


def _topic_fewshot(tc: dict) -> tuple[str, str]:
    """B: 仅 Few-shot"""
    system = "你是学术文献相关性评估专家。"
    ex_text = ""
    for i, ex in enumerate(TOPIC_FEW_SHOT):
        ex_text += (
            f"\n### 样例 {i+1}\n"
            f"研究主题：{tc['topic']}\n"
            f"论文标题：{ex['title']}\n"
            f"论文摘要：{ex['abstract']}\n"
            f"正确评分：{{\"relevance_score\": {ex['relevance_score']}, \"reason\": \"{ex['reason']}\"}}\n"
        )
    user = (
        f"请判断以下论文与研究主题的相关性，给出 0-1 之间的分数。\n\n"
        f"以下是几个评分样例供参考：{ex_text}\n"
        f"现在请为以下论文评分：\n\n"
        f"研究主题：{tc['topic']}\n\n"
        f"论文标题：{tc['title']}\n"
        f"论文摘要：{tc['abstract']}\n\n"
        f"返回格式：JSON {{\"relevance_score\": 0.XX, \"reason\": \"...\"}}"
    )
    return system, user


def _topic_optimized(tc: dict) -> tuple[str, str]:
    """C: 仅优化 — 当前项目 topic_relevance_filter.md"""
    system = "你是学术文献相关性评估专家。返回严格 JSON，不要其他文本。"
    user = (
        "# Topic Relevance Assessment\n\n"
        "你是学术文献相关性评估专家。判断每篇论文与研究主题的相关性。\n\n"
        "## 研究主题\n"
        f"{tc['topic']}\n\n"
        "## 论文列表\n"
        f"[{{\"paper_id\": \"test\", \"title\": \"{tc['title']}\", "
        f"\"abstract\": \"{tc['abstract'][:600]}\"}}]\n\n"
        "## 评估维度\n"
        "1. **领域匹配**：论文的应用领域是否与主题一致？\n"
        "2. **研究问题对齐**：论文解决的核心问题是否与主题相关？\n"
        "3. **方法相关性**：论文的方法是否适用于主题领域？（仅方法相似但领域不同不算相关）\n\n"
        "## 评分标准\n"
        "- 0.7-1.0：直接相关，研究内容与主题高度契合\n"
        "- 0.4-0.7：间接相关，提供重要背景或方法支撑\n"
        "- 0.0-0.4：弱相关，领域不同或仅方法层面相似\n\n"
        "## 输出格式\n"
        "返回严格 JSON 数组，不要其他文本：\n"
        "[{{\"paper_id\": \"...\", \"relevance_score\": 0.85, \"relevance_reason\": \"简要说明\"}}]"
    )
    return system, user


def _topic_full(tc: dict) -> tuple[str, str]:
    """D: 完整版 = 优化 + few-shot"""
    system = "你是学术文献相关性评估专家。返回严格 JSON，不要其他文本。"
    ex_text = ""
    for i, ex in enumerate(TOPIC_FEW_SHOT):
        ex_text += (
            f"\n### Few-Shot 样例 {i+1}\n"
            f"论文：{ex['title']}\n"
            f"摘要：{ex['abstract']}\n"
            f"→ 正确评分：relevance_score={ex['relevance_score']}, reason=\"{ex['reason']}\"\n"
        )
    user = (
        "# Topic Relevance Assessment\n\n"
        "你是学术文献相关性评估专家。判断每篇论文与研究主题的相关性。\n\n"
        "## 研究主题\n"
        f"{tc['topic']}\n\n"
        "## 论文列表\n"
        f"[{{\"paper_id\": \"test\", \"title\": \"{tc['title']}\", "
        f"\"abstract\": \"{tc['abstract'][:600]}\"}}]\n\n"
        "## 评估维度\n"
        "1. **领域匹配**：论文的应用领域是否与主题一致？\n"
        "2. **研究问题对齐**：论文解决的核心问题是否与主题相关？\n"
        "3. **方法相关性**：论文的方法是否适用于主题领域？（仅方法相似但领域不同不算相关）\n\n"
        "## 评分标准\n"
        "- 0.7-1.0：直接相关，研究内容与主题高度契合\n"
        "- 0.4-0.7：间接相关，提供重要背景或方法支撑\n"
        "- 0.0-0.4：弱相关，领域不同或仅方法层面相似\n\n"
        f"## 评分参考样例\n{ex_text}\n"
        "## 输出格式\n"
        "返回严格 JSON 数组，不要其他文本：\n"
        "[{{\"paper_id\": \"...\", \"relevance_score\": 0.85, \"relevance_reason\": \"简要说明\"}}]"
    )
    return system, user


# ============================================================
# 任务 2: Write Review (section_writing) — 基于真实项目数据
# ============================================================
# 数据来源: write_review_final.json record 5 (真实 write_section 输出)
# 系统 prompt: write_system.md (完整版本)
# Few-shot 样例: write_section.md 中的 Example 1 (综合优先) + Example 4 (文献[N]禁止)
# 引用列表: 从 record 5 的 Usable References 中截取前 8 条真实引用
# Evidence: 从 record 5 的 Evidence Cards 中截取前 5 张真实证据卡
# 段落规划: 从 record 5 的 Section Paragraph Plan 中截取

WRITE_TOPIC = "多模态大模型（图文 / 音视频）的对齐与微调方案综述"
WRITE_SECTION_TITLE = "多模态对齐范式：从结构化对齐到参数高效微调"
WRITE_SECTION_DESC = "系统梳理多模态模型对齐技术的演进路径，揭示结构化对齐方法（如Ovis、SpeechGPT）与参数高效微调（LoRA、训练免费方法）的范式差异，分析其在跨模态理解任务中的性能表现与适用边界。"
WRITE_DEBATES = "结构化对齐支持者认为显式设计能保证对齐质量，而参数高效方法倡导者强调其在资源效率和可扩展性上的优势，二者在适用场景上存在显著分歧。"

# 从 write_review_final.json record 5 中提取的真实引用（前 8 条）
WRITE_REAL_REFERENCES = """[1] Birong Pan, Yongqi Li, Weiyu Zhang et al., "A Survey on Training-free Alignment of Large Language Models", EMNLP.
[2] Zhixian Zhao, Haifeng Chen, Xi Li et al., "Improving Multimodal Emotion Recognition by Leveraging Acoustic Adaptation and Visual Alignment", MRAC@MM.
[3] Dong Zhang, Shimin Li, Xin Zhang et al., "SpeechGPT: Empowering Large Language Models with Intrinsic Cross-Modal Conversational Abilities", EMNLP.
[4] Shiyin Lu, Yang Li, Qing-Guo Chen et al., "Ovis: Structural Embedding Alignment for Multimodal Large Language Model", arXiv.
[5] Songtao Jiang, Yan Zhang, Ruizhe Chen et al., "Modality-Fair Preference Optimization for Trustworthy MLLM Alignment", IJCAI.
[6] Hao Yang, Lizhen Qu, Ehsan Shareghi et al., "Audio Is the Achilles' Heel: Red Teaming Audio Large Multimodal Models", NAACL.
[7] Raghav Sharma, Manan Mehta, Sai Tiger Raina, "RLHF: A comprehensive Survey for Cultural, Multimodal and Low Latency Alignment Methods", arXiv.
[8] Tianyi Bai, Hao Liang, Binwang Wan et al., "A Survey of Multimodal Large Language Model from A Data-centric Perspective", arXiv."""

# 从 write_review_final.json record 5 中提取的真实 Evidence（前 5 张）
WRITE_REAL_EVIDENCE = """[1] claim: 训练免费对齐方法为LLMs提供了无需重训练的对齐方案 | evidence: training-free alignment techniques leveraging in-context learning, decoding-time adjustments, and post-generation corrections | method: in-context learning, decoding-time adjustments, post-generation corrections | confidence: 0.85
[2] claim: SpeechGPT具备内在的跨模态对话能力，能感知和生成多模态内容 | evidence: The experimental results demonstrate that SpeechGPT has an impressive capacity to follow multi-modal human instructions | method: 三阶段训练策略（模态适应预训练、跨模态指令微调、模态链指令微调） | confidence: 0.85
[3] claim: Ovis通过结构对齐视觉和文本嵌入策略，提升了多模态大语言模型的性能 | evidence: Ovis employs a structured visual embedding table and probabilistic combination strategy | method: 结构化视觉嵌入表+概率组合对齐 | confidence: 0.85
[4] claim: RLHF综述覆盖文化、多模态和低延迟对齐方法 | evidence: comprehensive survey covering cultural, multimodal and low latency alignment methods for RLHF | method: 综述 | confidence: 0.75
[5] claim: MLLMs with visual instruction tuning achieved strong performance but remain limited in vision-centric tasks | evidence: MLLMs trained with visual instruction tuning achieved strong performance across diverse tasks | method: visual instruction tuning | confidence: 0.05"""

# 从 write_section.md 中提取的真实 few-shot 样例 —— Example 1 (Synthesis-First)
WRITE_FEW_SHOT_SYNTHESIS = """**示例 A（综合优先——对比策略）**：
深度学习在图像分类领域的演进呈现出从局部特征提取到全局建模的范式转变。早期CNN架构[1]通过卷积核捕获局部纹理特征，在标准基准上达到92%的分类准确率，但受限于感受野大小，难以建模长程依赖关系。Transformer架构[2]引入自注意力机制，将全局上下文建模能力提升至95%，但计算复杂度随图像分辨率二次增长。近期的混合架构[3]通过CNN提取局部特征后接入轻量化Transformer模块，在保持97%准确率的同时将计算开销降低40%，表明局部-全局特征的层次化融合是当前最具潜力的技术路线。"""

# 从 write_section.md 中提取的真实 few-shot 样例 —— Example 4 (文献[N]禁止)
WRITE_FEW_SHOT_CITATION = """**示例 B（引用位置——事实作主语 + [N]放句末）**：
注意力机制的核心思想是通过权重分配实现特征的选择性聚焦[1]。实验表明，该机制在长序列建模中的性能较传统RNN提升23%[2]。后续工作通过引入稀疏注意力将计算复杂度从O(n²)降至O(n log n)，使该架构在万级token序列上的推理成为可能[3]。

**示例 C（禁止的引用方式——文献[N]作主语，BANNED!）**：
文献[1]提出了基于注意力的机制。文献[2]通过实验证明了该方法的有效性。文献[3]进一步改进了该架构。
→ 以上写法被严格禁止。必须改为：事实/方法/结论在前，[N]在句末。"""


def _write_basic(tc: dict) -> tuple[str, str]:
    """A: 纯基础 — 最简单的写作指令"""
    system = "你是一个学术写作助手。"
    user = (
        f"研究主题：{WRITE_TOPIC}\n"
        f"章节：{WRITE_SECTION_TITLE}\n"
        f"章节描述：{WRITE_SECTION_DESC}\n\n"
        f"可用参考文献：\n{WRITE_REAL_REFERENCES}\n\n"
        f"可用证据：\n{WRITE_REAL_EVIDENCE}\n\n"
        f"请撰写约 500 字的综述正文。"
    )
    return system, user


def _write_fewshot(tc: dict) -> tuple[str, str]:
    """B: 仅 Few-shot — 基础 + write_section.md 的两组正反样例"""
    system = "你是一个学术写作助手。"
    user = (
        f"研究主题：{WRITE_TOPIC}\n"
        f"章节：{WRITE_SECTION_TITLE}\n"
        f"章节描述：{WRITE_SECTION_DESC}\n\n"
        f"以下是一些写作范例供参考：\n\n"
        f"{WRITE_FEW_SHOT_SYNTHESIS}\n\n"
        f"{WRITE_FEW_SHOT_CITATION}\n\n"
        f"可用参考文献：\n{WRITE_REAL_REFERENCES}\n\n"
        f"可用证据：\n{WRITE_REAL_EVIDENCE}\n\n"
        f"请参照范例的写作风格和引用格式，撰写约 500 字的综述正文。"
    )
    return system, user


def _write_optimized(tc: dict) -> tuple[str, str]:
    """C: 仅优化 — write_system.md 的核心约束（不含 few-shot 样例）"""
    system = "You write grounded Chinese academic literature reviews using only supplied evidence."
    user = (
        "# 综述章节写作\n\n"
        "你是一位精通学术写作的综述专家。请基于提供的证据撰写章节正文。所有内容必须使用中文。\n\n"
        f"## 研究主题\n{WRITE_TOPIC}\n\n"
        f"## 当前章节\n章节名称: {WRITE_SECTION_TITLE}\n"
        f"章节描述: {WRITE_SECTION_DESC}\n"
        f"学术争论: {WRITE_DEBATES}\n\n"
        "## 写作要求\n\n"
        "### 主题相关性（最高优先级）\n"
        "- 所有段落必须直接围绕研究主题展开\n"
        "- 每段的核心论点必须与研究主题建立明确联系\n"
        "### 综合优先（关键）\n"
        "- 段落必须围绕一个分析中心组织，多篇论文作为支撑证据\n"
        "- **禁止逐篇罗列论文**，必须按机制/方法类别/结论主题组织\n"
        "- 对比时明确异同及深层原因\n"
        "### 引用规则\n"
        "- 使用 [N] 数字引用格式，禁止\"文献[N]\"作主语\n"
        "- 每个事实性论断必须有引用支撑\n"
        "### 禁止的表达\n"
        "- 禁止正文中使用任何级别的标题（#、##、###）\n"
        "- 禁止聚类编号（聚类0、Cluster 1等）\n"
        "- 禁止\"综上所述、总之、值得注意的是\"等套话\n\n"
        f"## 可用参考文献（只可使用此列表中的论文）\n{WRITE_REAL_REFERENCES}\n\n"
        f"## 可用证据\n{WRITE_REAL_EVIDENCE}\n\n"
        "## 输出规则\n"
        "- 只输出章节正文（纯段落文本），不输出标题、参考文献列表\n"
        "- 约 500 字"
    )
    return system, user


def _write_full(tc: dict) -> tuple[str, str]:
    """D: 完整版 — write_system.md 核心约束 + write_section.md 的 few-shot 样例"""
    system = "You write grounded Chinese academic literature reviews using only supplied evidence."
    user = (
        "# 综述章节写作\n\n"
        "你是一位精通学术写作的综述专家。请基于提供的证据撰写章节正文。所有内容必须使用中文。\n\n"
        f"## 研究主题\n{WRITE_TOPIC}\n\n"
        f"## 当前章节\n章节名称: {WRITE_SECTION_TITLE}\n"
        f"章节描述: {WRITE_SECTION_DESC}\n"
        f"学术争论: {WRITE_DEBATES}\n\n"
        "## Few-Shot 写作样例\n\n"
        "以下是符合要求的写作示例，请参考其分析深度、综合策略和语言风格。特别注意引用格式：事实/方法/结论在前，[N]放在句末，**绝对禁止\"文献[N]\"作句子主语**：\n\n"
        f"{WRITE_FEW_SHOT_SYNTHESIS}\n\n"
        f"{WRITE_FEW_SHOT_CITATION}\n\n"
        "## 写作要求\n\n"
        "### 主题相关性（最高优先级）\n"
        "所有段落必须直接围绕研究主题展开。每段的核心论点必须与研究主题建立明确联系。\n"
        "### 综合优先（关键）\n"
        "**禁止逐篇罗列论文**，必须按机制/方法类别/结论主题组织。对比时明确异同及深层原因。\n"
        "### 引用规则（最高优先级）\n"
        "- 使用 [N] 数字引用格式，**绝对禁止\"文献[N]\"作句子主语**\n"
        "- 每个事实性论断必须有引用支撑\n"
        "- 引用必须在句末，例如 \"Ovis通过结构对齐提升了性能[4]。\"\n"
        "### 禁止的表达\n"
        "- 禁止正文中使用任何级别的标题（#、##、###）\n"
        "- 禁止聚类编号（聚类0、Cluster 1等）\n"
        "- 禁止\"综上所述、总之、值得注意的是\"等套话\n\n"
        f"## 可用参考文献（只可使用此列表中的论文，引用编号必须与列表一致）\n{WRITE_REAL_REFERENCES}\n\n"
        f"## 可用证据\n{WRITE_REAL_EVIDENCE}\n\n"
        "## 输出规则\n"
        "- 只输出章节正文（纯段落文本），不输出标题、参考文献列表\n"
        "- 约 500 字"
    )
    return system, user


# ============================================================
# 任务 3: KG Extraction — 知识图谱实体/关系提取
# ============================================================
KG_PAPER = {
    "id": "kg-test-01",
    "title": "Ovis: Structural Embedding Alignment for Multimodal Large Language Model",
    "abstract": (
        "We propose Ovis, a novel MLLM architecture designed to structurally align visual and "
        "textual embeddings. Ovis employs a structured visual embedding table and probabilistic "
        "combination strategy. Empirical evaluation on multimodal benchmarks shows superior "
        "performance over open-source models of similar scale."
    ),
}

KG_FEW_SHOT_EXAMPLE = {
    "entities": [
        {"paper_id": "example-01", "name": "Structural Embedding Alignment", "entity_type": "Method", "evidence": "structurally align visual and textual embeddings", "confidence": 0.9},
        {"paper_id": "example-01", "name": "Multimodal Large Language Model", "entity_type": "Concept", "evidence": "novel MLLM architecture", "confidence": 0.95},
        {"paper_id": "example-01", "name": "Visual-Textual Embedding Table", "entity_type": "Method", "evidence": "structured visual embedding table", "confidence": 0.85},
    ],
    "relations": [
        {"paper_id": "example-01", "source": "Structural Embedding Alignment", "target": "Visual-Textual Embedding Table", "relation_type": "uses", "evidence": "employs a structured visual embedding table", "confidence": 0.9},
        {"paper_id": "example-01", "source": "Structural Embedding Alignment", "target": "Multimodal Large Language Model", "relation_type": "improves", "evidence": "superior performance over open-source models", "confidence": 0.85},
    ],
}


def _kg_basic(tc: dict) -> tuple[str, str]:
    system = "You extract academic knowledge graphs. Return JSON only."
    user = (
        f"Extract entities and relations from this paper:\n\n"
        f"Paper ID: {KG_PAPER['id']}\n"
        f"Title: {KG_PAPER['title']}\n"
        f"Abstract: {KG_PAPER['abstract']}\n\n"
        f"Return JSON: {{\"entities\": [{{\"name\": \"...\", \"entity_type\": \"...\", \"evidence\": \"...\"}}], "
        f"\"relations\": [{{\"source\": \"...\", \"target\": \"...\", \"relation_type\": \"...\"}}]}}"
    )
    return system, user


def _kg_fewshot(tc: dict) -> tuple[str, str]:
    system = "You extract academic knowledge graphs. Return JSON only."
    user = (
        "Here is an example of correct KG extraction:\n\n"
        f"### Example\n"
        f"Input: Paper about 'Structural Embedding Alignment for MLLM'\n"
        f"Output:\n{json.dumps(KG_FEW_SHOT_EXAMPLE, ensure_ascii=False, indent=2)}\n\n"
        f"Now extract entities and relations from this paper:\n\n"
        f"Paper ID: {KG_PAPER['id']}\n"
        f"Title: {KG_PAPER['title']}\n"
        f"Abstract: {KG_PAPER['abstract']}\n\n"
        f"Return the same JSON structure."
    )
    return system, user


def _kg_optimized(tc: dict) -> tuple[str, str]:
    """C: 当前项目 kg_extraction.py 的 KG_EXTRACTION_USER_TEMPLATE"""
    system = (
        "You extract academic knowledge graphs for a review pipeline. "
        "Return strict UTF-8 JSON only. No markdown, no code fences, no explanations."
    )
    user = (
        "Extract normalized entities and relations that are useful for literature clustering and review writing.\n\n"
        "Schema:\n"
        "Allowed entity types: ResearchProblem, Method, Dataset, Metric, Material, Concept, Domain\n"
        "Allowed relation types: uses, evaluated_on, improves, applied_to, based_on, proposes, compares_with\n\n"
        "Return exactly one JSON object:\n"
        '{"entities": [{"paper_id": "...", "name": "...", "entity_type": "...", "aliases": [], '
        '"evidence": "short phrase", "confidence": 0.0}], '
        '"relations": [{"paper_id": "...", "source": "...", "target": "...", '
        '"relation_type": "uses", "evidence": "short phrase", "confidence": 0.0}]}\n\n'
        "Rules:\n"
        "- Output only valid JSON. No markdown, no code fences.\n"
        "- Use only the supplied paper. Do not invent paper ids.\n"
        "- Each entity name should be short, specific, and reusable.\n"
        "- Prefer ResearchProblem for tasks/challenges/objectives.\n"
        "- Prefer Concept for findings/theories/limitations.\n"
        "- Prefer Domain for application domains.\n"
        "- evidence must be a short phrase from the paper title or abstract.\n\n"
        f"Papers:\n[{{\"paper_id\": \"{KG_PAPER['id']}\", "
        f"\"title\": \"{KG_PAPER['title']}\", \"abstract\": \"{KG_PAPER['abstract']}\"}}]"
    )
    return system, user


def _kg_full(tc: dict) -> tuple[str, str]:
    """D: 完整版 = 优化 KG prompt + few-shot example"""
    system = _kg_optimized(tc)[0]
    user = (
        "Extract normalized entities and relations that are useful for literature clustering and review writing.\n\n"
        "Schema:\n"
        "Allowed entity types: ResearchProblem, Method, Dataset, Metric, Material, Concept, Domain\n"
        "Allowed relation types: uses, evaluated_on, improves, applied_to, based_on, proposes, compares_with\n\n"
        "Return exactly one JSON object:\n"
        '{"entities": [{"paper_id": "...", "name": "...", "entity_type": "...", "aliases": [], '
        '"evidence": "short phrase", "confidence": 0.0}], '
        '"relations": [{"paper_id": "...", "source": "...", "target": "...", '
        '"relation_type": "uses", "evidence": "short phrase", "confidence": 0.0}]}\n\n'
        "### Few-Shot Example\n"
        f"Input: Paper about 'Structural Embedding Alignment for MLLM'\n"
        f"Correct Output:\n{json.dumps(KG_FEW_SHOT_EXAMPLE, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "- Output only valid JSON. No markdown, no code fences.\n"
        "- Use only the supplied paper. Do not invent paper ids.\n"
        "- Each entity name should be short, specific, and reusable.\n"
        "- evidence must be a short phrase from the paper title or abstract.\n\n"
        f"Papers:\n[{{\"paper_id\": \"{KG_PAPER['id']}\", "
        f"\"title\": \"{KG_PAPER['title']}\", \"abstract\": \"{KG_PAPER['abstract']}\"}}]"
    )
    return system, user


# ============================================================
# 任务 4: Evidence Card — 证据卡片生成
# ============================================================
EVIDENCE_PAPER = {
    "id": "ev-test-01",
    "title": "Ovis: Structural Embedding Alignment for Multimodal Large Language Model",
    "abstract": (
        "We propose Ovis, a novel MLLM architecture designed to structurally align visual and "
        "textual embeddings. Ovis employs a structured visual embedding table and probabilistic "
        "combination strategy. Empirical evaluation on multimodal benchmarks shows superior "
        "performance over open-source models of similar scale. However, Ovis underperforms on "
        "fine-grained visual tasks such as object counting and spatial reasoning."
    ),
    "cluster_topics": "多模态对齐技术, 结构化嵌入对齐, 参数高效微调",
}

EVIDENCE_FEW_SHOT = """{
  "claim": "Ovis通过结构对齐视觉和文本嵌入策略，提升了多模态大语言模型的性能",
  "evidence_span": "Ovis employs a structured visual embedding table and probabilistic combination strategy. Empirical evaluation on multimodal benchmarks shows superior performance over open-source models of similar scale.",
  "method": "结构化视觉嵌入表 + 概率组合对齐策略",
  "metric": "多模态基准测试性能（优于同规模开源模型）",
  "limitation": "在细粒度视觉任务（如物体计数和空间推理）上表现受限",
  "confidence": 0.85
}"""


def _evidence_basic(tc: dict) -> tuple[str, str]:
    system = "你是一个学术证据分析专家。"
    user = (
        f"请分析以下论文并生成证据卡片。\n\n"
        f"标题: {EVIDENCE_PAPER['title']}\n"
        f"摘要: {EVIDENCE_PAPER['abstract']}\n"
        f"社区主题: {EVIDENCE_PAPER['cluster_topics']}\n\n"
        f"返回 JSON: {{\"claim\": \"...\", \"evidence_span\": \"...\", \"method\": \"...\", \"metric\": \"...\", \"limitation\": \"...\", \"confidence\": 0.XX}}"
    )
    return system, user


def _evidence_fewshot(tc: dict) -> tuple[str, str]:
    system = "你是一个学术证据分析专家。"
    user = (
        f"请分析以下论文并生成证据卡片。\n\n"
        f">好的证据卡片样例：\n```json\n{EVIDENCE_FEW_SHOT}\n```\n\n"
        f"现在请为以下论文生成证据卡片：\n\n"
        f"标题: {EVIDENCE_PAPER['title']}\n"
        f"摘要: {EVIDENCE_PAPER['abstract']}\n"
        f"社区主题: {EVIDENCE_PAPER['cluster_topics']}\n\n"
        f"返回相同结构的 JSON。"
    )
    return system, user


def _evidence_optimized(tc: dict) -> tuple[str, str]:
    """C: 当前项目 evidence_generation.py 的 EVIDENCE_SYSTEM_PROMPT + EVIDENCE_PROMPT"""
    system = (
        "你是一个学术证据分析专家。你的任务是从学术论文中提取结构化的证据信息。\n\n"
        "对于每篇论文，你需要生成一个证据卡片，包含：\n"
        "- claim: 论文的核心主张或贡献\n"
        "- evidence_span: 支持主张的关键证据片段（直接引用或摘要）\n"
        "- method: 使用的主要方法\n"
        "- metric: 使用的评估指标\n"
        "- limitation: 论文提到的局限性\n"
        "- confidence: 证据的置信度 (0-1)\n\n"
        "输出格式（严格 JSON）：\n"
        '{"claim": "核心主张", "evidence_span": "证据片段", "method": "使用方法", '
        '"metric": "评估指标", "limitation": "局限性", "confidence": 0.85}'
    )
    user = (
        f"请分析以下论文并生成证据卡片。\n\n"
        f"标题: {EVIDENCE_PAPER['title']}\n"
        f"摘要: {EVIDENCE_PAPER['abstract']}\n"
        f"社区主题: {EVIDENCE_PAPER['cluster_topics']}\n\n"
        f"请以 JSON 格式输出。"
    )
    return system, user


def _evidence_full(tc: dict) -> tuple[str, str]:
    """D: 完整版 = 当前 prompt + few-shot example"""
    system = _evidence_optimized(tc)[0]
    user = (
        f"请分析以下论文并生成证据卡片。\n\n"
        f"> 好的证据卡片样例（请参考其结构、深度和措辞）：\n```json\n{EVIDENCE_FEW_SHOT}\n```\n\n"
        f"现在请分析以下论文：\n\n"
        f"标题: {EVIDENCE_PAPER['title']}\n"
        f"摘要: {EVIDENCE_PAPER['abstract']}\n"
        f"社区主题: {EVIDENCE_PAPER['cluster_topics']}\n\n"
        f"请以 JSON 格式输出。"
    )
    return system, user


# ========================================================================
# 任务注册
# ========================================================================
TASK_REGISTRY = {
    "topic_relevance": {
        "label": "Topic 相关性评分",
        "test_cases": TOPIC_TEST_CASES,
        "builders": {
            "A_pure_basic": ("纯基础", _topic_basic),
            "C_optimized_only": ("当前优化 Prompt (topic_relevance_filter.md)", _topic_optimized),
        },
        "metrics": ["relevance_score"],
    },
    "write_review": {
        "label": "综述章节写作",
        "test_cases": [{"id": "W01", "dummy": True}],
        "builders": {
            "A_pure_basic": ("纯基础", _write_basic),
            "B_fewshot_only": ("仅 Few-shot (write_section.md Example)", _write_fewshot),
            "C_optimized_only": ("仅优化 Prompt (write_system.md 约束)", _write_optimized),
            "D_full": ("完整版 (优化+Few-shot)", _write_full),
        },
        "metrics": ["writing_quality"],
    },
    "kg_extraction": {
        "label": "知识图谱提取",
        "test_cases": [{"id": "K01", "dummy": True}],
        "builders": {
            "A_pure_basic": ("纯基础", _kg_basic),
            "C_optimized_only": ("当前优化 Prompt (kg_extraction.py)", _kg_optimized),
        },
        "metrics": ["entity_count", "relation_count", "valid_json"],
    },
    "evidence_card": {
        "label": "证据卡片生成",
        "test_cases": [{"id": "E01", "dummy": True}],
        "builders": {
            "A_pure_basic": ("纯基础", _evidence_basic),
            "C_optimized_only": ("当前优化 Prompt (evidence_generation.py)", _evidence_optimized),
        },
        "metrics": ["has_claim", "has_method", "has_limitation", "has_metric", "valid_json"],
    },
}


# ========================================================================
# 评估函数
# ========================================================================
def parse_score(content: str) -> float | None:
    """从 topic_relevance 返回中提取 relevance_score"""
    text = content.strip().replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'relevance_score["\s:]*([\d.]+)', text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None

    if isinstance(data, list):
        for item in data:
            s = item.get("relevance_score")
            if isinstance(s, (int, float)):
                return float(s)
    elif isinstance(data, dict):
        s = data.get("relevance_score")
        if isinstance(s, (int, float)):
            return float(s)
    return None


def parse_json_safe(content: str) -> dict | list | None:
    """安全解析 JSON"""
    text = content.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'[\{\[].*[\}\]]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None


def eval_topic_relevance(result: dict, tc: dict) -> dict:
    """评估 topic_relevance 结果"""
    score = parse_score(result["content"]) if not result["error"] else None
    gt = tc["ground_truth"]
    abs_err = abs(score - gt) if score is not None else None
    return {
        "predicted_score": score,
        "absolute_error": round(abs_err, 4) if abs_err is not None else None,
        "correct_high": (gt >= 0.7 and (score or 0) >= 0.7) if score is not None else False,
        "correct_low": (gt < 0.3 and (score or 0) < 0.3) if score is not None else False,
    }


def eval_kg_extraction(result: dict, tc: dict) -> dict:
    """评估 KG 提取结果"""
    data = parse_json_safe(result["content"])
    if data is None:
        return {"entity_count": 0, "relation_count": 0, "valid_json": False}
    entities = data.get("entities", []) if isinstance(data, dict) else []
    relations = data.get("relations", []) if isinstance(data, dict) else []
    # 检查 entity 质量：有 name 和 entity_type
    valid_entities = sum(1 for e in entities if isinstance(e, dict) and e.get("name") and e.get("entity_type"))
    valid_relations = sum(1 for r in relations if isinstance(r, dict) and r.get("source") and r.get("target") and r.get("relation_type"))
    return {
        "entity_count": len(entities),
        "relation_count": len(relations),
        "valid_entity_count": valid_entities,
        "valid_relation_count": valid_relations,
        "valid_json": True,
    }


def eval_evidence_card(result: dict, tc: dict) -> dict:
    """评估 evidence card 质量"""
    data = parse_json_safe(result["content"])
    if data is None or not isinstance(data, dict):
        return {"has_claim": False, "has_method": False, "has_limitation": False, "has_metric": False, "valid_json": False}
    return {
        "has_claim": bool(data.get("claim")),
        "has_method": bool(data.get("method")),
        "has_limitation": bool(data.get("limitation")),
        "has_metric": bool(data.get("metric")),
        "valid_json": True,
    }


def eval_write_review(result: dict, tc: dict) -> dict:
    """评估 writing 质量 — 基于规则的定性指标"""
    content = result.get("content", "")
    # 去掉 think block 后再评估
    if "<think>" in content:
        idx = content.find("</think>")
        if idx >= 0:
            content = content[idx + 8 :].strip()
    return {
        "output_chars": len(content),
        "has_citation": bool(re.search(r'\[\d+\]', content)),
        "has_literature_subject": bool(re.search(r'文献\[', content)),  # 负面指标：文献[N] 作主语
        "has_cluster_number": bool(re.search(r'[Cc]luster\s*\d+|聚类\s*\d+', content)),
        "paragraph_count": len([p for p in content.split('\n\n') if p.strip() and len(p.strip()) > 50]),
        "has_chinese_content": bool(re.search(r'[一-鿿]{20,}', content)),
    }


# ========================================================================
# 主流程
# ========================================================================
def run_one(task_name: str, task_info: dict, tc: dict, vk: str, vlabel: str, build_fn) -> dict:
    system, user = build_fn(tc)
    resp = call_llm(system, user)

    base = {
        "task": task_name,
        "task_label": task_info["label"],
        "test_id": tc.get("id", "N/A"),
        "variant": vk,
        "variant_label": vlabel,
        "system_prompt_chars": len(system),
        "user_prompt_chars": len(user),
        "prompt_tokens": resp["prompt_tokens"],
        "completion_tokens": resp["completion_tokens"],
        "total_tokens": resp["total_tokens"],
        "latency_ms": resp["latency_ms"],
        "content": resp["content"][:500] if resp["content"] else "",
        "content_full": resp["content"] if resp["content"] else "",
        "error": resp["error"] or "",
    }

    # 任务特定评估
    if task_name == "topic_relevance":
        ev = eval_topic_relevance(resp, tc)
    elif task_name == "kg_extraction":
        ev = eval_kg_extraction(resp, tc)
    elif task_name == "evidence_card":
        ev = eval_evidence_card(resp, tc)
    elif task_name == "write_review":
        ev = eval_write_review(resp, tc)
    else:
        ev = {}

    base.update(ev)
    # 也保存 gt 用于 topic
    if "ground_truth" in tc:
        base["ground_truth"] = tc["ground_truth"]
    if "category" in tc:
        base["category"] = tc["category"]

    return base


def save_detailed_csv(results: list[dict]):
    """保存完整详细结果"""
    fieldnames = [
        "task", "task_label", "test_id", "variant", "variant_label",
        "category", "ground_truth", "predicted_score", "absolute_error",
        "output_chars", "entity_count", "relation_count",
        "has_claim", "has_method", "has_limitation", "has_metric",
        "has_citation", "has_literature_subject", "has_chinese_content",
        "valid_json", "paragraph_count",
        "system_prompt_chars", "user_prompt_chars",
        "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms",
        "content", "error",
    ]
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"详细结果: {OUTPUT_CSV} ({os.path.getsize(OUTPUT_CSV):,} bytes)")


def save_summary(results: list[dict]):
    """生成按任务×variant的汇总对比 CSV"""
    rows = []
    for task_name, task_info in TASK_REGISTRY.items():
        for vk, (vlabel, _) in task_info["builders"].items():
            v_results = [r for r in results if r["task"] == task_name and r["variant"] == vk]
            if not v_results:
                continue

            row = {"任务": task_info["label"], "Prompt 变体": vlabel}

            if task_name == "topic_relevance":
                valid = [r for r in v_results if r.get("absolute_error") is not None]
                errors = [r["absolute_error"] for r in valid]
                row["MAE↓"] = round(sum(errors)/len(errors), 4) if errors else None
                row["RMSE↓"] = round((sum(e**2 for e in errors)/len(errors))**0.5, 4) if errors else None
                row["高相关命中 (≥0.7)"] = sum(1 for r in valid if r.get("correct_high"))
                row["低相关命中 (<0.3)"] = sum(1 for r in valid if r.get("correct_low"))

            elif task_name == "kg_extraction":
                row["平均实体数"] = sum(r.get("entity_count", 0) for r in v_results) // len(v_results)
                row["平均关系数"] = sum(r.get("relation_count", 0) for r in v_results) // len(v_results)
                row["有效实体数"] = sum(r.get("valid_entity_count", 0) for r in v_results) // len(v_results)
                row["有效关系数"] = sum(r.get("valid_relation_count", 0) for r in v_results) // len(v_results)
                row["JSON有效性"] = sum(1 for r in v_results if r.get("valid_json"))

            elif task_name == "evidence_card":
                row["有claim"] = sum(1 for r in v_results if r.get("has_claim"))
                row["有method"] = sum(1 for r in v_results if r.get("has_method"))
                row["有limitation"] = sum(1 for r in v_results if r.get("has_limitation"))
                row["有metric"] = sum(1 for r in v_results if r.get("has_metric"))
                row["JSON有效性"] = sum(1 for r in v_results if r.get("valid_json"))

            elif task_name == "write_review":
                row["输出字数"] = sum(r.get("output_chars", 0) for r in v_results) // len(v_results)
                row["有数字引用"] = sum(1 for r in v_results if r.get("has_citation"))
                row["文献[N]作主语(负面)"] = sum(1 for r in v_results if r.get("has_literature_subject"))
                row["聚类编号(负面)"] = sum(1 for r in v_results if r.get("has_cluster_number"))
                row["有效段落数"] = sum(r.get("paragraph_count", 0) for r in v_results) // len(v_results)

            row["平均Tokens"] = sum(r["total_tokens"] for r in v_results) // len(v_results)
            row["平均延迟ms"] = sum(r["latency_ms"] for r in v_results) // len(v_results)
            row["失败数"] = sum(1 for r in v_results if r["error"])

            rows.append(row)

    with open(OUTPUT_SUMMARY, "w", encoding="utf-8-sig", newline="") as f:
        if rows:
            # Build union of all keys so all columns appear
            all_keys = []
            seen = set()
            for r in rows:
                for k in r:
                    if k not in seen:
                        all_keys.append(k)
                        seen.add(k)
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            writer.writerows(rows)
    print(f"汇总: {OUTPUT_SUMMARY}")


def main():
    # 构建所有 task×case×variant
    all_tasks = []
    for task_name, task_info in TASK_REGISTRY.items():
        for tc in task_info["test_cases"]:
            for vk, (vlabel, build_fn) in task_info["builders"].items():
                all_tasks.append((task_name, task_info, tc, vk, vlabel, build_fn))

    total = len(all_tasks)
    print(f"{'='*70}")
    print(f"多任务 Prompt 消融实验")
    print(f"任务数: {len(TASK_REGISTRY)}  总调用: {total}  模型: {MODEL}")
    print(f"{'='*70}")

    all_results = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(run_one, tn, ti, tc, vk, vl, bf): (ti["label"], tc.get("id", "?"), vl)
            for tn, ti, tc, vk, vl, bf in all_tasks
        }
        for future in as_completed(futures):
            task_label, test_id, vlabel = futures[future]
            result = future.result()
            all_results.append(result)

            status = "✅" if not result["error"] else "❌"
            info = ""
            if result.get("absolute_error") is not None:
                info = f"err={result['absolute_error']:.3f}"
            elif result.get("entity_count", 0) > 0:
                info = f"ent={result['entity_count']} rel={result['relation_count']}"
            elif result.get("has_claim") is not None:
                info = f"claim={result['has_claim']} method={result['has_method']}"
            elif result.get("output_chars", 0) > 0:
                info = f"chars={result['output_chars']} cite={result['has_citation']}"

            print(
                f"  [{status}] {task_label:<20} | {vlabel:<28} | {info} "
                f"| tok={result['total_tokens']} lat={result['latency_ms']}ms",
                flush=True,
            )

    total_elapsed = int((time.time() - t_start) * 1000)
    print(f"\n总耗时: {total_elapsed/1000:.1f}s  总tokens: {sum(r['total_tokens'] for r in all_results)}")

    # 保存
    save_detailed_csv(all_results)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    save_summary(all_results)

    # ======================== 打印对比 ========================
    print(f"\n{'='*90}")
    print("📊 消融实验结果对比")
    print(f"{'='*90}")

    for task_name, task_info in TASK_REGISTRY.items():
        print(f"\n### {task_info['label']}")
        print(f"{'指标':<24}", end="")
        for vk, (vl, _) in task_info["builders"].items():
            print(f" | {vl:<22}", end="")
        print()

        v_results_map = {}
        for vk in task_info["builders"]:
            v_results_map[vk] = [r for r in all_results if r["task"] == task_name and r["variant"] == vk]

        if task_name == "topic_relevance":
            for metric_label, fn in [
                ("MAE↓", lambda rs: round(sum(r["absolute_error"] for r in rs if r.get("absolute_error") is not None) / max(sum(1 for r in rs if r.get("absolute_error") is not None), 1), 4)),
                ("RMSE↓", lambda rs: round((sum(r["absolute_error"]**2 for r in rs if r.get("absolute_error") is not None) / max(sum(1 for r in rs if r.get("absolute_error") is not None), 1))**0.5, 4)),
                ("高相关命中", lambda rs: f"{sum(1 for r in rs if r.get('correct_high'))}/{sum(1 for r in rs if r.get('ground_truth', 0)>=0.7)}"),
                ("低相关命中", lambda rs: f"{sum(1 for r in rs if r.get('correct_low'))}/{sum(1 for r in rs if r.get('ground_truth', 0)<0.3)}"),
            ]:
                print(f"{metric_label:<24}", end="")
                for vk in task_info["builders"]:
                    val = fn(v_results_map[vk])
                    print(f" | {str(val):<22}", end="")
                print()

        elif task_name == "kg_extraction":
            for metric_label, key in [
                ("实体数", "entity_count"), ("关系数", "relation_count"),
                ("有效实体", "valid_entity_count"), ("有效关系", "valid_relation_count"),
            ]:
                print(f"{metric_label:<24}", end="")
                for vk in task_info["builders"]:
                    rs = v_results_map[vk]
                    avg = sum(r.get(key, 0) for r in rs) // max(len(rs), 1)
                    print(f" | {str(avg):<22}", end="")
                print()

        elif task_name == "evidence_card":
            for metric_label, key in [
                ("有claim", "has_claim"), ("有method", "has_method"),
                ("有limitation", "has_limitation"), ("有metric", "has_metric"),
                ("JSON有效", "valid_json"),
            ]:
                print(f"{metric_label:<24}", end="")
                for vk in task_info["builders"]:
                    rs = v_results_map[vk]
                    cnt = sum(1 for r in rs if r.get(key))
                    print(f" | {cnt}/{len(rs):<20}", end="")
                print()

        elif task_name == "write_review":
            for metric_label, key in [
                ("输出字数", "output_chars"), ("有数字引用", "has_citation"),
                ("文献[N]主语(负面)", "has_literature_subject"),
                ("聚类编号(负面)", "has_cluster_number"),
                ("有效段落数", "paragraph_count"),
            ]:
                print(f"{metric_label:<24}", end="")
                for vk in task_info["builders"]:
                    rs = v_results_map[vk]
                    if key in ("has_citation", "has_literature_subject", "has_cluster_number"):
                        cnt = sum(1 for r in rs if r.get(key))
                        print(f" | {cnt}/{len(rs):<20}", end="")
                    else:
                        avg = sum(r.get(key, 0) for r in rs) // max(len(rs), 1)
                        print(f" | {str(avg):<22}", end="")
                print()

        # 平均 tokens
        print(f"{'平均Tokens':<24}", end="")
        for vk in task_info["builders"]:
            rs = v_results_map[vk]
            avg = sum(r["total_tokens"] for r in rs) // max(len(rs), 1)
            print(f" | {str(avg):<22}", end="")
        print()

    print(f"\n输出文件:")
    print(f"  详细结果: {OUTPUT_CSV}")
    print(f"  汇总对比: {OUTPUT_SUMMARY}")
    print(f"  JSON结果: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
