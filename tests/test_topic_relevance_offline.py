"""
离线测试：topic_relevance_filter prompt 评测

测试目标：
1. 验证 prompt 对真实论文的评分是否合理
2. 对比 DB 中的 LLM 输出与重新运行的结果
3. 检测 prompt 对"领域不相关"论文的识别能力

测试论文：
- [13] 54358610 - Slope stability prediction under seismic loading based on the EO-LightGBM algorithm
  → DB 评分 0.85，但写入内容引用为"交流微电网瞬态稳定性"（幻觉）
- [14] dfb8fb08 - Comparative Analysis of Support Moment Variability in Double-Span Continuous Beams
  → DB 中 LLM 调用被取消，无评分，写入内容引用为"神经网络模型在处理岩土体非线性响应"（幻觉）
- [18] 65d54663 - Rock‐Mass Quality Classification and 3D Mechanical Modeling Based on Oblique Photography Data
  → DB 评分 0.85，写入内容引用为"胆固醇修饰β-环糊精封装模型"（幻觉）
"""

import asyncio
import json
import os
import sys

import httpx

# ── 配置 ──────────────────────────────────────────────────────────
TOPIC = "数值仿真在边坡工程的应用"

TEST_PAPERS = [
    {
        "ref_number": 13,
        "paper_id": "54358610-8327-42c9-9b08-ec77f03f7b03",
        "title": "Slope stability prediction under seismic loading based on the EO-LightGBM algorithm",
        "abstract": (
            "Predicting the stability of slopes under seismic conditions is critical for "
            "geological hazard prevention and infrastructure safety. This study proposes an "
            "optimized prediction model based on EO-LightGBM to enhance the accuracy of slope "
            "stability assessment. A dataset containing 96 numerical simulation cases was "
            "constructed using FLAC3D, incorporating key influencing factors such as slope angle, "
            "inclination angle, slope height, rock mechanical parameters, and hard-to-soft rock "
            "thickness ratio."
        ),
        "db_score": 0.85,
        "db_reason": "论文基于FLAC3D数值模拟数据构建边坡稳定性预测模型，直接应用数值仿真技术解决边坡工程中的地震稳定性评估问题，方法与领域均高度契合主题",
        "hallucinated_context": "Zhenxi Wu等[13]在交流微电网瞬态稳定性研究中发现，传统时域仿真方法在处理多尺度耦合问题时存在计算效率瓶颈",
    },
    {
        "ref_number": 14,
        "paper_id": "dfb8fb08-8e2f-4068-89a4-481dc046d516",
        "title": "Comparative Analysis of Support Moment Variability in Double-Span Continuous Beams under Symmetric Loading Using Classical and Finite Element Methods",
        "abstract": (
            "Accurate estimation of support moments in continuous beams is essential for ensuring "
            "structural safety, serviceability, and material efficiency in modern reinforced "
            "concrete design. Despite advancements in computational modeling, inconsistencies "
            "persist between classical analytical predictions and finite element (FE) simulations, "
            "particularly at internal supports where stress concentrations and boundary "
            "idealizations strongly influence results."
        ),
        "db_score": None,
        "db_reason": None,
        "hallucinated_context": "Yutai Nie等[14]指出，神经网络模型在处理岩土体非线性响应时，其预测误差在极端工况下可达18.7%",
    },
    {
        "ref_number": 18,
        "paper_id": "65d54663-5111-4a0a-a634-94cd20ef9b73",
        "title": "Rock‐Mass Quality Classification and 3D Mechanical Modeling Based on Oblique Photography Data",
        "abstract": (
            "In order to analyze rock slope stability, efficient rock‐mass characterization and "
            "3D numerical modelling are very important. Unmanned aerial vehicle (UAV) oblique "
            "photogrammetry, with its low cost, high accuracy, and wide coverage, is commonly "
            "used in geological surveys and provides a foundation for rock‐mass quality assessment. "
            "Utilizing UAV oblique photogrammetry data, this study proposed a comprehensive "
            "workflow achieve efficient 3D mechanical modeling."
        ),
        "db_score": 0.85,
        "db_reason": "论文提出基于无人机倾斜摄影数据的三维机械建模方法，直接涉及岩体质量评估与边坡稳定性分析，其核心数值建模技术与数值仿真在边坡工程中的应用高度契合",
        "hallucinated_context": "Pawel Misiak等[18]提出的胆固醇修饰β-环糊精封装模型，通过热重分析与分子模拟验证了物理约束机制的有效性",
    },
]

# ── Prompt 模板 ───────────────────────────────────────────────────
SYSTEM_PROMPT = "你是学术文献相关性评估专家。返回严格 JSON，不要其他文本。"

USER_PROMPT_TEMPLATE = """# Topic Relevance Assessment

你是学术文献相关性评估专家。判断每篇论文与研究主题的相关性。

## 研究主题
{topic}

## 论文列表
{papers_json}

## 评估维度
1. **领域匹配**：论文的应用领域是否与主题一致？
2. **研究问题对齐**：论文解决的核心问题是否与主题相关？
3. **方法相关性**：论文的方法是否适用于主题领域？（仅方法相似但领域不同不算相关）

## 评分标准
- 0.7-1.0：直接相关，研究内容与主题高度契合
- 0.4-0.7：间接相关，提供重要背景或方法支撑
- 0.0-0.4：弱相关，领域不同或仅方法层面相似

## 输出格式
返回严格 JSON 数组，不要其他文本：
[{{"paper_id": "...", "relevance_score": 0.85, "relevance_reason": "简要说明"}}]
"""


def build_user_prompt(papers: list[dict]) -> str:
    papers_json = json.dumps(
        [
            {
                "paper_id": p["paper_id"],
                "title": p["title"],
                "abstract": p["abstract"],
            }
            for p in papers
        ],
        ensure_ascii=False,
        indent=2,
    )
    return USER_PROMPT_TEMPLATE.format(topic=TOPIC, papers_json=papers_json)


async def call_llm(
    provider_base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
) -> str:
    """调用 LLM API（兼容 OpenAI 格式）"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{provider_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def parse_llm_output(raw: str) -> list[dict]:
    """解析 LLM 返回的 JSON"""
    raw = raw.strip()
    # 去掉可能的 markdown 代码块
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)
    return json.loads(raw)


async def test_individual_papers():
    """逐篇测试每篇论文的相关性评分"""
    print("=" * 80)
    print("测试 1：逐篇论文相关性评估")
    print("=" * 80)

    # 从环境变量或 .env 读取 LLM 配置
    base_url = os.environ.get("LLM_BASE_URL", "https://ai.gitee.com/v1")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "DeepSeek-V3")

    if not api_key:
        print("[WARN] 未设置 LLM_API_KEY 环境变量，跳过 LLM 调用测试")
        print("       设置后重新运行: $env:LLM_API_KEY='your-key'; python tests/test_topic_relevance_offline.py")
        print()
        _print_paper_analysis()
        return

    for paper in TEST_PAPERS:
        print(f"\n{'─' * 60}")
        print(f"Reference [{paper['ref_number']}]")
        print(f"  Paper ID: {paper['paper_id']}")
        print(f"  Title: {paper['title']}")
        print(f"  DB Score: {paper['db_score']}")
        print(f"  DB Reason: {paper['db_reason']}")
        print(f"  幻觉上下文: {paper['hallucinated_context']}")
        print()

        user_prompt = build_user_prompt([paper])
        try:
            raw = await call_llm(base_url, api_key, model, SYSTEM_PROMPT, user_prompt)
            results = parse_llm_output(raw)
            if results:
                r = results[0]
                print(f"  [LLM 输出] score={r.get('relevance_score')}, reason={r.get('relevance_reason')}")
            else:
                print(f"  [LLM 输出] 空结果")
        except Exception as e:
            print(f"  [LLM 调用失败] {e}")


def _print_paper_analysis():
    """仅打印论文分析（不需要 LLM 调用）"""
    print("\n" + "=" * 80)
    print("论文分析（无需 LLM 调用）")
    print("=" * 80)

    for paper in TEST_PAPERS:
        print(f"\n{'─' * 60}")
        print(f"Reference [{paper['ref_number']}]")
        print(f"  Paper ID: {paper['paper_id']}")
        print(f"  Title: {paper['title']}")
        print(f"  Abstract (前200字): {paper['abstract'][:200]}...")
        print()
        print(f"  DB 评分: {paper['db_score']}")
        print(f"  DB 理由: {paper['db_reason']}")
        print()
        print(f"  写入内容中的幻觉上下文:")
        print(f"    {paper['hallucinated_context']}")
        print()
        _analyze_mismatch(paper)


def _analyze_mismatch(paper: dict):
    """分析论文实际内容与幻觉引用之间的差异"""
    title_lower = paper["title"].lower()
    abstract_lower = paper["abstract"].lower()
    hallucinated = paper["hallucinated_context"]

    print(f"  [差异分析]")

    # 检查领域匹配
    if "slope" in title_lower or "landslide" in title_lower:
        actual_domain = "边坡工程/地质工程"
    elif "beam" in title_lower or "continuous" in title_lower:
        actual_domain = "结构工程（连续梁）"
    elif "rock" in title_lower and "classification" in title_lower:
        actual_domain = "岩体质量分类/3D建模"
    else:
        actual_domain = "未知"

    print(f"    实际领域: {actual_domain}")

    # 检查幻觉内容
    if "微电网" in hallucinated or "microgrid" in hallucinated.lower():
        print(f"    幻觉领域: 电力系统/微电网")
        print(f"    ❌ 严重幻觉：论文实际是关于「{actual_domain}」，但被引用为「微电网瞬态稳定性」")
    elif "神经网络" in hallucinated and "岩土" in hallucinated:
        print(f"    幻觉领域: 机器学习/岩土工程")
        print(f"    ❌ 严重幻觉：论文实际是关于「{actual_domain}」，但被引用为「神经网络岩土响应」")
    elif "胆固醇" in hallucinated or "环糊精" in hallucinated:
        print(f"    幻觉领域: 化学/药物化学")
        print(f"    ❌ 严重幻觉：论文实际是关于「{actual_domain}」，但被引用为「胆固醇修饰环糊精」")

    # 评估 prompt 评分是否合理
    if paper["db_score"] is not None:
        score = paper["db_score"]
        if "beam" in title_lower:
            print(f"    ⚠️  Prompt 评分 {score} 偏高：连续梁分析与边坡工程领域不同")
        elif "rock" in title_lower and "slope" in abstract_lower:
            print(f"    ✓  Prompt 评分 {score} 合理：岩体质量分类与边坡稳定性分析直接相关")
        elif "slope" in title_lower:
            print(f"    ✓  Prompt 评分 {score} 合理：边坡稳定性预测与主题高度契合")


async def test_batch_evaluation():
    """批量测试：3篇论文一起评估"""
    print("\n" + "=" * 80)
    print("测试 2：批量论文相关性评估（模拟实际 pipeline 行为）")
    print("=" * 80)

    base_url = os.environ.get("LLM_BASE_URL", "https://ai.gitee.com/v1")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "DeepSeek-V3")

    if not api_key:
        print("[SKIP] 未设置 LLM_API_KEY，跳过批量测试")
        return

    user_prompt = build_user_prompt(TEST_PAPERS)
    print(f"\n发送 {len(TEST_PAPERS)} 篇论文给 LLM 批量评估...")
    print(f"Topic: {TOPIC}")
    print(f"Model: {model}")
    print()

    try:
        raw = await call_llm(base_url, api_key, model, SYSTEM_PROMPT, user_prompt)
        results = parse_llm_output(raw)
        print(f"LLM 返回 {len(results)} 条结果:")
        for r in results:
            pid = r.get("paper_id", "?")
            score = r.get("relevance_score", "?")
            reason = r.get("relevance_reason", "?")
            # 找到对应的 ref_number
            ref = next((p["ref_number"] for p in TEST_PAPERS if p["paper_id"] == pid), "?")
            print(f"  [{ref}] score={score}")
            print(f"       reason={reason}")
    except Exception as e:
        print(f"[LLM 调用失败] {e}")


async def main():
    print("Topic Relevance Filter 离线评测")
    print(f"研究主题: {TOPIC}")
    print()

    await test_individual_papers()
    await test_batch_evaluation()

    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    print("""
关键发现：

1. Reference [13] (EO-LightGBM边坡稳定性预测):
   - Prompt 评分 0.85 ✓ 合理（论文确实关于边坡数值仿真）
   - 但写入综述时被错误引用为"交流微电网瞬态稳定性研究" ❌ 幻觉
   - 根因：写作阶段 LLM 混淆了引用编号与论文内容的对应关系

2. Reference [14] (连续梁支撑弯矩分析):
   - DB 中 LLM 调用被取消，无评分 ⚠️
   - 论文领域为结构工程（连续梁），与边坡工程不直接相关
   - 但仍被引用为"神经网络模型在处理岩土体非线性响应" ❌ 幻觉
   - 根因：论文通过了相关性过滤（可能因"finite element"关键词），但写作时内容被编造

3. Reference [18] (岩体质量分类与3D建模):
   - Prompt 评分 0.85 ✓ 合理（论文确实关于岩体建模与边坡稳定性）
   - 但写入综述时被错误引用为"胆固醇修饰β-环糊精封装模型" ❌ 严重幻觉
   - 根因：写作阶段 LLM 完全编造了与论文无关的化学领域内容

问题定位：
  - topic_relevance_filter 的 prompt 本身工作基本正常
  - 核心问题在 write_review 阶段：LLM 在写作时混淆了引用编号与论文内容
  - 这是"引用幻觉"而非"相关性评分幻觉"
""")


if __name__ == "__main__":
    asyncio.run(main())
