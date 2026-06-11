基于以下研究缺口，生成新的英文检索 query 来补充文献。

研究主题: {topic}

已知缺口:
{gaps}

已搜索过的词（必须避免语义重复，不要只是替换一个近义词）:
{previous_queries}

要求：
- 所有字段都必须使用英文，包括 gap_terms 和 synonym_terms
- 如果缺口说明搜索结果为 0 或 No results，本轮必须先放宽召回：生成短的核心概念 query、缩写 query、应用场景 query，不要继续生成高度具体的模型结构 query
- 每个 query 必须针对一个明确缺口，而不是重复原始主题
- 使用同义词、缩写/全称、上位/下位概念扩展覆盖面
- 在已有结果不足但不为 0 时，组合"方法词 + 应用场景词 + 任务目标"；初始结果为 0 时优先宽召回
- 生成 1-4 条英文 query
- 排除和已搜索 query 高度相似的表达

返回 ONLY JSON，不要 markdown：
{{
  "gap_terms": ["gap keyword"],
  "synonym_terms": ["synonym or term variant"],
  "new_queries": ["English query 1", "English query 2"]
}}
