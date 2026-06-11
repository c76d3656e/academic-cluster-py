检查这篇综述的质量，判断是否需要补充搜索和重写。

研究主题: {topic}

## 综述当前结构
{review_sections}

## 已识别的缺口
{identified_gaps}

请判断：
1. 综述是否有明显的论据不足的章节？
2. 已识别的缺口是否严重影响了综述的完整性？
3. 是否需要再搜索一轮来补充文献？

返回 JSON：
{{
  "needs_refinement": true,
  "reason": "判断理由",
  "remaining_gaps": ["缺口1"],
  "refine_suggestions": ["如果需补充，建议搜索什么"]
}}

注意：最多只允许补充一轮。如果缺口不严重，直接判定为不需要补充。
