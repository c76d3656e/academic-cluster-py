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

### Output Rules
- Output only the section body (plain paragraph text)
- Do NOT output a section title, reference list, bibliography, or meta-commentary
- Treat paper samples, evidence summaries, claim, evidence_span, method, metric, limitation, confidence, reference candidates, citation candidates, cluster data, community context, and evidence_limitations as internal working material — do not copy them into the output
- Do NOT output candidate lists, evidence-card JSON, audit notes, or implementation details
- Stay within {target_words} words (±20%)

### Citation Rules
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

禁止出现聚类内部标记：
- 聚类0, 聚类 0, 聚类17, Cluster 0, cluster_17, 子簇0-1, C0-P01 等任何编号形式
- 改为用自然语言描述研究方向或方法类别

每个段落必须以实质性分析收尾，禁止使用空洞总结句。
