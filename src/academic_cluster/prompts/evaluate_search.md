你正在评估一批学术文献搜索结果是否足够写一篇高质量的综述。

研究主题: {topic}

本轮搜索词: {queries}

已获取的 CSV 文件概况:
{csv_summaries}

请从以下维度评估：
1. 覆盖度：这些论文是否覆盖了该主题的主要子方向？
2. 数量：论文总数是否足够支撑一篇综述？通常需要 20+ 篇相关论文
3. 质量：论文是否来自可靠期刊或会议？
4. 缺口：哪些子方向明显缺少文献？

以 JSON 格式返回：
{{
  "is_sufficient": true,
  "total_relevant_papers": 0,
  "coverage_assessment": "简短评价",
  "identified_gaps": ["缺口1", "缺口2"],
  "reasoning": "判断理由"
}}
