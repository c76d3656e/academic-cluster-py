基于以下研究缺口和聚类统计信息，生成针对性的英文检索 query 来补充薄弱子主题文献。

研究主题: {topic}

## 已识别的研究缺口
{gaps}

## 薄弱聚类信息（这些子主题目前论文数量不足）
{weak_clusters}

每个聚类的 top_terms 是其核心关键词，representative_papers 是聚类中心附近的代表性论文。

要求：
- 所有字段都必须使用英文，包括 cluster_terms、gap_terms 和 synonym_terms
- 每条 query 必须针对一个薄弱聚类或明确研究缺口
- 将聚类 top_terms、缺口描述、代表论文标题中的方法/应用词结合
- 主动加入常见同义词、缩写/全称、上位/下位概念，但不能变成泛泛搜索
- 避免与已搜索 query 语义重复，不要只是替换一个近义词
- 每个薄弱聚类最多生成 1-2 条 query，总数 1-6 条
- 每条 query 使用英文，适合普通全文搜索 API

已搜索过的词（避免重复）:
{previous_queries}

返回 ONLY JSON，不要 markdown：
{{
  "cluster_terms": ["cluster keyword"],
  "gap_terms": ["gap keyword"],
  "synonym_terms": ["synonym or term variant"],
  "new_queries": ["English query 1", "English query 2"]
}}
