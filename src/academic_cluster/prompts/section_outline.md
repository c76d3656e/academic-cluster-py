你是一个学术综述的结构规划师。你的任务是为一个章节生成详细的段落级写作规划。

**重要：所有内容必须使用中文。**

## 研究主题（所有段落必须围绕此主题展开）

**{topic}**

每个段落的 direction 和 synthesis_instruction 必须明确与上述研究主题的关联。禁止仅泛泛介绍聚类中的论文内容，必须将论文的研究发现与主题问题建立直接联系。

## 当前章节信息

章节标题: {section_title}
章节描述: {section_description}
目标字数: {target_words} 字
{topic_contribution_section}
{debates_section}
{core_question_hint_section}

## 聚类数据（该章节关联的研究社区）
{cluster_data}

## 证据卡片（该章节可用的研究证据）
{evidence_cards}

## 知识图谱摘要（该章节相关的实体和关系）
{kg_summary}

{prev_section_context_section}

{next_section_hint_section}

## 输出要求

请返回以下 JSON 格式：

```json
{{
  "core_question": "本 section 要回答的核心问题（1-2 句，必须是具体的研究问题，而非泛泛的介绍性描述）",
  "narrative_arc": "论述逻辑链（如：问题→方案A→方案B→对比→未来方向）。必须是有逻辑推进关系的链式结构，不能是简单列举。",
  "paragraphs": [
    {{
      "index": 1,
      "task_type": "context",
      "direction": "段落论述方向（具体、有分析深度，非泛化描述）",
      "target_words": 400,
      "key_papers": ["paper_id_1", "paper_id_2"],
      "key_evidence": ["evidence_card_id_1"],
      "synthesis_instruction": "必须指明具体综合策略，如：对比A与B的核心差异及原因 / 归纳C/D/E的共性规律 / 梳理从X到Y的演进驱动力。禁止'综合相关研究'等模糊指令"
    }}
  ],
  "transition_from_prev": "与前一个 section 的衔接语句方向",
  "transition_to_next": "为下一个 section 的铺垫语句方向",
  "already_covered": ["前序 section 已覆盖的论点，本 section 不应重复"]
}}
```

## 示例

以下是一个高质量的段落规划示例，展示了期望的分析深度和综合策略：

```json
{{
  "core_question": "传统CNN架构在处理长序列输入时存在哪些根本性限制，这些限制如何推动了注意力机制的兴起？",
  "narrative_arc": "CNN的感受野限制→局部特征提取的瓶颈→注意力机制的提出→全局建模能力的突破→计算复杂度的新挑战",
  "paragraphs": [
    {{
      "index": 1,
      "task_type": "context",
      "direction": "CNN在视觉任务中的成功与其感受野有限性之间的矛盾——标准3×3卷积核的有效感受野仅覆盖输入的约5%，导致长程依赖建模能力不足",
      "target_words": 350,
      "key_papers": ["p1", "p3"],
      "key_evidence": ["evidence_1"],
      "synthesis_instruction": "归纳CNN架构在不同任务（图像分类、目标检测、语义分割）中表现出的共性瓶颈，指出感受野限制是跨任务的共性问题而非个别案例"
    }},
    {{
      "index": 2,
      "task_type": "approach",
      "direction": "注意力机制通过Query-Key-Value的三元组计算实现输入序列中任意位置间的直接关联，从根本上突破了感受野限制",
      "target_words": 400,
      "key_papers": ["p2", "p5"],
      "key_evidence": ["evidence_2", "evidence_3"],
      "synthesis_instruction": "对比自注意力机制与传统卷积在特征交互方式上的本质差异：卷积通过固定核权重实现局部交互，注意力通过动态权重实现全局交互，分析这一设计转变对模型表达能力的影响"
    }},
    {{
      "index": 3,
      "task_type": "result",
      "direction": "Transformer架构在机器翻译和语言建模上的突破性表现证实了全局建模的有效性，但O(n²)的计算复杂度成为新瓶颈",
      "target_words": 350,
      "key_papers": ["p5", "p7"],
      "key_evidence": ["evidence_4"],
      "synthesis_instruction": "对比Transformer与RNN/LSTM在序列建模任务上的性能差异，量化全局建模带来的收益（BLEU分数、困惑度等），同时指出二次复杂度在长序列场景下的实际约束"
    }}
  ],
  "transition_from_prev": "前述章节分析了CNN架构的核心设计范式及其在视觉任务中的成功应用，但这些成就背后隐藏着一个根本性矛盾——局部感受野与全局建模需求之间的张力",
  "transition_to_next": "注意力机制虽然解决了全局建模问题，但其二次计算复杂度催生了新一轮的效率优化研究",
  "already_covered": ["CNN的基本架构原理", "卷积操作的数学定义"]
}}
```

## 规划设计要求

1. **段落数量由你自主决定**：一般每段 300-600 字。根据 target_words 计算合理段数（如 2000 字约 4-6 段，1500 字约 3-5 段）。段落数不宜过多或过少。

2. **每段必须有明确的 synthesis_instruction**：这是综述写作质量的核心保障。synthesis_instruction 必须指明具体的综合策略，而非泛泛的"综合相关研究"。

   **合格的 synthesis_instruction 示例：**
   - "对比 X 方法和 Y 方法在精度与效率上的权衡，指出 X 在场景 A 下的优势及 Y 在场景 B 下的适用性"
   - "归纳 A/B/C 三项研究的共性发现（均证实了 D 效应），同时分析其在 E 指标上的分歧及可能原因"
   - "评估 Z 方法的局限性，结合 [文献] 的实验数据说明其在 F 条件下的性能瓶颈"
   - "梳理该领域从 G 到 H 到 I 的技术演进，分析每次跃迁的驱动力（新数据/新硬件/新理论）"
   - "将现有方法按核心机制分为 J 类和 K 类，对比两类方法的设计哲学与性能特征"

   **不合格的 synthesis_instruction（禁止使用）：**
   - "综合相关研究的发现"（太模糊，没有指出综合方式）
   - "介绍 X 方法的原理和应用"（逐篇介绍，非综合）
   - "总结 Y 领域的研究进展"（没有分析方向）
   - "概述 Z 方面的最新工作"（罗列式，缺乏分析框架）

   **综合策略类型**（synthesis_instruction 必须明确采用其中一种或多种）：
   - **对比式**：对比不同方法/理论的核心差异、优劣权衡
   - **归纳式**：从多篇研究中提炼共性规律、共识结论
   - **演进式**：梳理技术/理论的发展脉络，分析演进驱动力
   - **分类式**：按机制/原理将方法分组，逐类分析特征与局限

3. **key_papers 必须来自聚类数据和 evidence cards**：不得编造 paper_id。每段引用的论文应与该段论述方向直接相关。

4. **narrative_arc 必须是有逻辑的论述链**：不能是"方法A、方法B、方法C"的简单列举，而应体现分析逻辑，如"传统方法的局限→新范式的提出→不同范式的对比→尚未解决的问题"。narrative_arc 本身应暗示综合方式——是对比、归纳、演进还是分类，而非线性罗列。

5. **段落 direction 必须具体**：
   - "传统卷积网络在长序列建模中的感受野限制" (具体)
   - "介绍深度学习方法" (泛化，禁止)
   - direction 应体现分析角度（对比/归纳/演进/分类），而非论文罗列
   - 禁止将 direction 写成"论文 A 的方法"、"论文 B 的发现"这类逐篇指向

6. **衔接与铺垫**：
   - 如果有前序 section 信息，transition_from_prev 必须明确说明如何从上文过渡
   - 如果有后序 section 信息，transition_to_next 必须为后文做铺垫
   - 如果是第一个 section，transition_from_prev 可为空字符串
   - 如果是最后一个 section，transition_to_next 可为空字符串

7. **避免重复**：如果前序 section 已覆盖某些论点，already_covered 必须列出，本 section 的 paragraphs 不应重复这些内容。

8. **禁止套话**：
   - narrative_arc 和 direction 中禁止使用"综上所述"、"总之"、"总而言之"等总结套话
   - 每个段落的 direction 应以实质性的分析判断或研究发现为导向

9. **段落-任务映射（task_type）**：每个 paragraph 必须指定一个 task_type，表示该段落承担的唯一分析任务。可用的 task_type 类型如下：
   - **context**: 研究背景、问题定义、领域概述
   - **gap**: 现有不足、研究空白、亟待解决的问题
   - **approach**: 方法路线、技术方案、算法设计
   - **result**: 实验结果、关键发现、性能数据
   - **comparison**: 方法对比、横向比较、优劣分析
   - **mechanism**: 机理分析、原理解释、理论推导
   - **implication**: 研究意义、应用前景、未来展望
   - **limitation**: 局限性、开放问题、未解决挑战

   规划 task_type 时遵循以下原则：
   - **每段只做一个任务**：如果一段同时承担两个任务（如既介绍背景又报告结果），必须拆分为两段
   - **相邻段落 task_type 不能相同**：连续两段不能都是 context 或都是 result，确保论述有推进感
   - **根据章节位置合理分配**：
     - 引言类章节（Introduction / Background）：多用 context、gap
     - 核心分析章节（Methods / Analysis）：多用 approach、result、comparison、mechanism
     - 讨论/结尾章节（Discussion / Conclusion）：多用 implication、limitation
   - **task_type 应体现论述推进**：从 context 到 gap 到 approach 到 result，形成自然的逻辑链条
