# 文献筛选Prompt规范

## 筛选标准

### 输入格式

论文以CSV格式提供，包含以下字段：
- title: 论文标题
- abstract: 摘要
- authors: 作者
- year: 发表年份
- venue: 期刊/会议名称
- doi: DOI标识符
- if: 影响因子

### 筛选规则

1. **相关性**：论文必须与研究主题直接相关或提供重要背景支撑
2. **质量门槛**：影响因子 >= 3 或来自知名会议
3. **时效性**：优先选择近5年文献，经典文献可适当放宽
4. **去重**：同一论文在不同来源中出现时保留信息最完整的一条

### 输出格式

筛选结果必须输出标准JSON结构：

```json
{{
  "selected_papers": [
    {{
      "title": "论文标题",
      "authors": "作者列表",
      "year": 2024,
      "venue": "期刊名",
      "doi": "10.xxxx/xxxxx",
      "relevance_score": 0.95,
      "relevance_reason": "与主题高度相关的原因"
    }}
  ],
  "rejected_count": 150,
  "selected_count": 50,
  "coverage_notes": "覆盖情况说明"
}}
```

## 注意事项

- relevance_score 范围 0-1，0.7以上入选
- relevance_reason 简要说明入选/排除理由
- 不编造论文信息
- 保留所有原始字段，不做修改
