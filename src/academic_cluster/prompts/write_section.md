You are writing one section of an academic literature review. Output in Chinese.

## Research Topic
{topic}

## Review Title
{review_title}

## Current Section
Section name: {section_title}
Section description: {section_description}
Target word count: {target_words} words

## Related Cluster Data
{cluster_data}

## Related Paper Samples
{sample_papers}

## Usable References (cite ONLY from this list)
These are real papers extracted from academic databases, numbered with section-local indices. Only cite papers from this list. Do not fabricate.

{references}

## Evidence Cards (specific findings you may cite)
The following research evidence is relevant to this section and may be used to support your arguments:

{evidence_cards}

## Section Paragraph Plan
{section_outline}

## Previous Content Summary (do not repeat)
{prev_summary}

## Next Section Preview
{next_outline}

## Writing Requirements

### Topic Relevance (Highest Priority)
- The research topic is stated at the top of this prompt. ALL paragraphs must directly relate to this topic.
- Each paragraph's central thesis must explicitly connect to the research topic — do not merely describe papers in a cluster without linking them to the topic question.
- Every factual claim must not only cite a paper but also explain its relevance to the research topic.
- If a paragraph's content cannot be connected to the topic, either rewrite it to establish the connection or remove it entirely.

### Academic Style
- Use formal, rigorous academic Chinese
- Demonstrate deep domain understanding through precise technical terminology
- Vary sentence structure: mix long and short sentences, avoid monotony
- Ensure logical progression between paragraphs, not mere juxtaposition

### Paragraph Variety (Critical)
- **Never start consecutive paragraphs with the same word, phrase, or sentence pattern.** If the previous paragraph began with "随着...", the next one MUST use a different opening (e.g., start with a finding, a contrast, a method name, or a direct statement).
- Banned consecutive-paragraph opening patterns:
  - Two paragraphs starting with "随着..."
  - Two paragraphs starting with "在..."
  - Two paragraphs starting with "基于..."
  - Two paragraphs starting with "然而..." or "此外..."
  - Two paragraphs starting with a paper citation (e.g., "Huang等[3]...")
- When writing, check the FIRST SENTENCE of the "Already written" paragraphs and choose a completely different opening structure for your current paragraph.
- Good opening strategies (rotate between these): direct factual claim, contrast with previous point, method/concept name as subject, question-driven transition, temporal/evolutionary marker, quantitative finding.

### Analytical Depth
- A literature review is NOT a summary list. You must ANALYZE: compare methods, evaluate strengths/weaknesses, reveal trends
- Surface **consensus** vs. **controversy**: which conclusions are widely accepted? which are still debated?
- Identify **driving forces** behind method evolution: why did method A give way to method B? insufficient accuracy? new data types?
- When studies conflict, explicitly state the contradiction and analyze possible causes

### Synthesis-First (Critical)
Each paragraph must be organized around a central analytical thesis, with multiple papers as supporting evidence.

**BANNED — paper-by-paper listing:**
- "Author A [1] proposed X. Author B [2] proposed Y. Author C [3] proposed Z."
- Sequential sentences each introducing a different paper without analytical connection
- Simply juxtaposing findings without pointing out similarities and differences

**REQUIRED — thematic synthesis:**
- Organize paragraphs by mechanism, method category, or conclusion theme — not by individual papers
- When comparing, explicitly state similarities, differences, and underlying reasons
- Use comparative, inductive, evolutionary, or taxonomic synthesis strategies

### Few-Shot Examples

Below are correct and incorrect examples demonstrating key writing rules.

#### Example 1: Synthesis-First (Comparative Strategy)

**BAD (paper-by-paper listing — BANNED):**
> 张三等[1]提出了一种基于CNN的图像分类方法，准确率达到92%。李四等[2]提出了一种基于Transformer的方法，准确率达到95%。王五等[3]提出了一种混合架构方法，准确率达到97%。
>
> *问题：逐篇罗列，无分析关联，无综合对比。*

**GOOD (thematic synthesis — REQUIRED):**
> 深度学习在图像分类领域的演进呈现出从局部特征提取到全局建模的范式转变。早期CNN架构[1]通过卷积核捕获局部纹理特征，在标准基准上达到92%的分类准确率，但受限于感受野大小，难以建模长程依赖关系。Transformer架构[2]引入自注意力机制，将全局上下文建模能力提升至95%，但计算复杂度随图像分辨率二次增长。近期的混合架构[3]通过CNN提取局部特征后接入轻量化Transformer模块，在保持97%准确率的同时将计算开销降低40%，表明局部-全局特征的层次化融合是当前最具潜力的技术路线。
>
> *优点：按"局部→全局→融合"的演进线索组织，对比三种方法的优劣，分析演进驱动力。*

#### Example 2: Citation Placement

**BAD (citations used as subject — BANNED):**
> [1]提出了基于注意力的机制。[2]通过实验证明了该方法的有效性。[3]进一步改进了该架构。

**GOOD (citations support claims — REQUIRED):**
> 注意力机制的核心思想是通过权重分配实现特征的选择性聚焦[1]。实验表明，该机制在长序列建模中的性能较传统RNN提升23%[2]。后续工作通过引入稀疏注意力将计算复杂度从O(n²)降至O(n log n)，使该架构在万级token序列上的推理成为可能[3]。

#### Example 3: Paragraph Opening Variety

**BAD (consecutive paragraphs start with same pattern):**
> 随着深度学习技术的发展，CNN在图像领域取得了突破[1]。
> 随着硬件算力的提升，Transformer架构逐渐成为主流[2]。
> *问题：连续两段以"随着..."开头，句式单调。*

**GOOD (varied openings):**
> 卷积神经网络通过层次化特征提取在图像识别任务中实现了突破性进展[1]。
> GPU集群算力的指数级增长为Transformer架构的工程落地提供了硬件基础[2]。
> *优点：第一段以方法名作主语，第二段以硬件因素作主语，开头结构不同。*

#### Example 4: "文献[N]" Pattern — ABSOLUTELY BANNED

The pattern "文献[N]" (literature [N]) is NEVER allowed in any form — not as subject, not as possessive modifier, not in parentheses. Every occurrence below is a fatal error.

**ALL OF THESE ARE BANNED:**
> ❌ 文献[25]的混合建模研究显示，通过整合机理模型与数据驱动方法，可将效率提升40%[25]。
> ❌ 文献[30]的两阶段浸出-沉淀法使磷回收率超过98%[30]。
> ❌ 文献[42]指出，多尺度耦合计算中仍存在35%的算力浪费[42]。
> ❌ （文献[24][28]已证实该方法的有效性）
> ❌ 根据文献[15]的实验结果，该方法优于基线模型[15]。
>
> *问题：所有"文献[N]"的变体都被禁止——无论是作主语、所有格修饰语、还是介词宾语。*

**REQUIRED — rewrite using one of these three patterns:**

Pattern A — **事实/方法作主语 + [N] 放句末**:
> ✅ 混合建模研究显示，通过整合机理模型与数据驱动方法，可将尾矿处理效率提升40%以上[25]。
> ✅ 两阶段浸出-沉淀法使磷酸盐尾矿磷回收率超过98%，纯度达到97.9%[30]。

Pattern B — **作者名 + [N] 引导**:
> ✅ Zhang等[25]的混合建模研究表明，整合机理模型与数据驱动方法可将效率提升40%以上。
> ✅ Li等[30]提出的两阶段浸出-沉淀法使磷回收率超过98%。

Pattern C — **"有研究/已有工作" + [N]**:
> ✅ 有研究[25]通过混合建模方法证实，整合机理模型与数据驱动方法可将效率提升40%以上。
> ✅ 已有工作[30]表明，两阶段浸出-沉淀法可使磷回收率超过98%。

#### Example 5: Body Text Subtitles — ABSOLUTELY BANNED

The body must contain ONLY flowing paragraphs. Any form of subtitle, heading, or section divider is a fatal error.

**ALL OF THESE ARE BANNED:**
> ❌ 传统处置模式与资源化路径的环境经济差异——以处置成本、碳排放与资源收益的量化对比揭示核心矛盾
> ❌ 一、研究背景与问题提出
> ❌ ## 方法论演进
> ❌ 【技术路线对比】
> ❌ （一）传统处置方法
> ❌ > 方法概述：本文从三个维度...
>
> *问题：正文不允许任何形式的标题、小标题、分隔符、段落标注。读者不需要段落的"标签"，段落本身的内容就应该清楚表达其主题。*

**REQUIRED — 直接写段落，不加任何标题前缀：**
> ✅ 传统处置模式以安全填埋和尾矿库堆存为主，虽能短期控制风险，但长期占用土地资源且存在溃坝隐患。资源化路径则通过提取有价组分实现变废为宝，但初期投资成本较高。两类模式在处置成本、碳排放和资源收益三个维度上呈现出显著差异...

### Output Rules
- Output only the section body (plain paragraph text)
- Do NOT output a section title, reference list, bibliography, or meta-commentary
- **禁止在正文中使用任何级别的标题**（#、##、###、#### 等）。正文只允许纯段落文本，段落之间用空行分隔。不要添加"研究背景"、"方法概述"、"实验结果"等小标题
- **禁止任何形式的段落标注或分隔符**：包括但不限于"一、二、三"、"（一）（二）"、"【】"、破折号标题（"——以XX揭示XX"）、冒号标签（"方法概述："）等。正文必须是纯段落流
- Treat paper samples, evidence summaries, claim, evidence_span, method, metric, limitation, confidence, reference candidates, citation candidates, cluster data, community context, and evidence_limitations as internal working material — do not copy them into the output
- Do NOT output candidate lists, evidence-card JSON, audit notes, or implementation details
- Stay within {target_words} words (±20%)

### Citation Rules

**⚠️ 最高优先级规则 — 禁止使用"文献[N]"格式：**
- ❌ 绝对禁止使用"文献[N]"作为句子主语、所有格或宾语
- ❌ "文献[25]的CLANN方法..."、"文献[23]的生成式AI方法..." 都是致命错误
- ✅ 必须改为：方法名作主语 + [N] 放句末（如 "CLANN方法通过聚类分析实现了...[25]"）
- ✅ 或使用作者名引导（如 "Zhang等[25]提出的CLANN方法..."）

- Every factual claim must be supported by a citation
- Aim for 2-4 citations per paragraph; do not cite for the sake of citing
- When multiple papers support the same point, merge citations: [1,2]; when they disagree, use contrastive analysis
- Use 10-20 evidence-backed papers per section; if evidence is insufficient, you may use fewer, but must rewrite or remove claims that lack supporting references
- Every sentence containing a factual claim, method comparison, metric, trend, limitation, or conclusion must be supported by a [N] citation in the same or adjacent sentence
- A paper may be cited multiple times for different claims, but never cite numbers outside the provided list
- Citation [N] must correspond 1:1 with the paper_id, title, and evidence_card_id in the reference list and paper samples
- Never attribute a claim from paper A using paper B's [N], even if both discuss similar topics
- Never fabricate references, authors, years, journals, DOI, or paper conclusions
- **Format**: Use [N] numeric citations only (e.g., [1], [1,2,3], [1-5])
- **Banned**: Author-year format (e.g., (Friedman, 2024), (Smith et al., 2023))
- **Banned**: Using paper_id (e.g., p1, p2) as citation numbers
- **Banned**: Adjacent citation blocks like [24][28] — merge as [24,28]
- **Banned**: Wrapping citations in parentheses (e.g., "（文献[24][28]已证实...）") — integrate into sentence syntax
- **Banned**: Starting a sentence with "文献[N]" or using "文献[N]" as subject

#### Citation Position Examples (MUST follow):

**Correct:**
- ✅ `多尺度耦合计算中仍存在35%的算力浪费，主要源于异构计算单元间的通信开销[42]。` — [N] at end of claim
- ✅ `结合概率密度演化方程，实现岩体参数的时序演化模拟[43]。` — [N] at end of method statement
- ✅ `该方法在Exascale架构上展现出显著优势，计算精度较传统方法提升22.7%[52]。` — [N] at end of conclusion
- ✅ `Zhang等[18]提出了基于自注意力的加速器` — author name leads + [N]
- ✅ `HAR-AttenNet利用多头注意力机制解决了这一问题[18]` — [N] at sentence end
- ✅ `Transformer在长序列建模中表现优异，但计算复杂度较高[18,19]` — [N] after claim

**Absolutely forbidden (highest priority rules):**
- ❌ NEVER start a sentence with "文献[N]": `文献[42]指出...`, `文献[43]通过...` are all banned
- ❌ NEVER use [N] as subject or object of a sentence: `[18]提出了...` is banned
- ❌ NEVER wrap citations in parentheses: `（文献[24][28]已证实...）` is banned
- ❌ `Rocco Palmitessa等人在《Accelerating hydrodynamic simulations...》中提出了...` — missing [N], uses 《》 marks
- ❌ NEVER mention an author name or paper title without an accompanying [N]: `Rocco Palmitessa等人在《...》中提出了...` is banned — write `Rocco Palmitessa等人[18]提出了...` instead
- ❌ NEVER use 《》(Chinese book title marks) to wrap paper titles — use [N] citation only

**Required pattern:**
- ✅ State the fact/method/conclusion first, then place [N] before the end punctuation
- ✅ `多尺度耦合计算中仍存在35%的算力浪费[42]。`
- ✅ `结合概率密度演化方程实现时序演化模拟[43]。`
- ✅ `Zhang等[18]提出了基于自注意力的加速器。` (author-led is OK)
- ✅ `HAR-AttenNet利用多头注意力机制解决了这个问题[18]。`

### 禁止使用的表达

禁止使用的空洞短语：
- 从方法论角度, 从技术演进角度, 从理论角度, 从应用角度
- 从宏观层面, 从微观层面, 在理论层面, 在实践层面
- 在技术层面, 在方法层面, 在应用层面, 在模型层面
- 在数据层面, 在性能层面, 在效率层面, 在架构层面
- 在算法层面, 在系统层面

禁止使用的总结性连接词：
- 综上所述, 总之, 总而言之, 综上, 概括而言, 总的来说, 整体而言, 由此可见

**严禁出现聚类/社区内部标记（最高优先级规则）：**
- 禁止任何形式的聚类编号：聚类0, 聚类 0, 聚类14, 聚类17, Cluster 0, cluster_17, 子簇0-1, C0-P01, 社区0, 社区 3 等
- 禁止引用聚类编号作为研究方向描述（如"聚类14的水深反演模型"）
- **必须**用自然语言描述研究方向或方法类别（如"水深反演研究"、"基于深度学习的目标检测方法"）
- 这些编号仅用于内部数据组织，出现在正文中会被视为严重错误

每个段落必须以实质性分析收尾，禁止使用空洞总结句。
