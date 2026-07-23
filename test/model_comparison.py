"""
多模型 Write Review 对比脚本
----------------------------------------
用相同的 prompt 调用 glm-4-9b-chat 和 internlm3-8b-instruct，
与服务器上 qwen3-8b 的原始结果进行对比。

API: Gitee AI (https://ai.gitee.com/v1)
框架: litellm
"""
import json
import csv
import re
import os
import time
import sys
from datetime import datetime
from litellm import completion

# ======================== 配置 ========================
API_BASE = "https://ai.gitee.com/v1"
API_KEY = os.environ.get("GITEE_AI_API_KEY")
if not API_KEY:
    raise RuntimeError("GITEE_AI_API_KEY is required")

MODELS_TO_TEST = [
    "glm-4-9b-chat",
    "internlm3-8b-instruct",
]

# 原始模型（服务器使用的）
ORIGINAL_MODEL = "qwen3-8b"

# 最大 tokens
MAX_TOKENS = 4096

# 请求间隔（秒），避免 API 限流
DELAY_BETWEEN_CALLS = 2

# 输入输出文件
INPUT_JSON = os.path.join(os.path.dirname(__file__), "write_review_final.json")
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "model_comparison.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(__file__), "model_comparison.json")


# ======================== Prompt 解析 ========================
def parse_langchain_prompt(raw_prompt: str) -> tuple[str, str]:
    """
    解析 LangChain 格式的 prompt:
    [SystemMessage(content='...', additional_kwargs={}, response_metadata={}),
     HumanMessage(content='...', additional_kwargs={}, response_metadata={})]

    返回 (system_content, human_content)
    """
    # 提取 SystemMessage content
    sys_start_marker = "SystemMessage(content='"
    sys_start = raw_prompt.find(sys_start_marker)
    if sys_start == -1:
        # 没有 system message 的情况
        return "", raw_prompt

    sys_start += len(sys_start_marker)
    sys_end_marker = "', additional_kwargs={}"
    sys_end = raw_prompt.find(sys_end_marker, sys_start)

    if sys_end == -1:
        system_content = raw_prompt[sys_start:]
    else:
        system_content = raw_prompt[sys_start:sys_end]

    # 提取 HumanMessage content
    human_marker = "HumanMessage(content='"
    human_start = raw_prompt.find(human_marker)
    if human_start == -1:
        return system_content, ""

    human_start += len(human_marker)
    human_end_marker = "', additional_kwargs={}, response_metadata={})]"
    human_end = raw_prompt.rfind(human_end_marker)

    if human_end == -1:
        human_content = raw_prompt[human_start:]
    else:
        human_content = raw_prompt[human_start:human_end]

    # 将 Python 转义字符转换为实际字符
    # 注意: JSON 中的 \\n 已经是字面的 \n（Python 字符串转义）
    # 但 raw_prompt 中的内容可能还有额外的转义
    system_content = _unescape_python_str(system_content)
    human_content = _unescape_python_str(human_content)

    return system_content, human_content


def _unescape_python_str(s: str) -> str:
    """处理 Python 字符串转义序列"""
    # 处理常见的转义
    s = s.replace("\\n", "\n")
    s = s.replace("\\t", "\t")
    s = s.replace("\\'", "'")
    s = s.replace('\\"', '"')
    s = s.replace("\\\\", "\\")
    return s


# ======================== LLM 调用 ========================
def call_model(model_name: str, system_content: str, user_content: str,
               max_tokens: int = MAX_TOKENS, retries: int = 3) -> dict:
    """
    使用 litellm 调用指定模型
    返回 {"content": str, "tokens": int, "model": str, "error": str|None, "latency_ms": int}
    """
    messages = []
    if system_content and system_content.strip():
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": user_content})

    # 构建 litellm model 名称（openai/ 前缀表示 OpenAI 兼容 API）
    litellm_model = f"openai/{model_name}"

    for attempt in range(retries):
        start_time = time.time()
        try:
            response = completion(
                model=litellm_model,
                messages=messages,
                api_base=API_BASE,
                api_key=API_KEY,
                max_tokens=max_tokens,
                timeout=300,
            )
            elapsed = int((time.time() - start_time) * 1000)

            content = response.choices[0].message.content
            usage = response.usage

            return {
                "content": content,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "model": response.model,
                "error": None,
                "latency_ms": elapsed,
            }
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            err_msg = str(e)[:500]
            if attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"⚠️ 重试 {attempt+1}/{retries-1} (等待{wait}s): {err_msg[:80]}...")
                time.sleep(wait)
            else:
                return {
                    "content": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "model": model_name,
                    "error": err_msg,
                    "latency_ms": elapsed,
                }


# ======================== 主流程 ========================
def main():
    # 加载原始数据
    print(f"加载数据: {INPUT_JSON}")
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        calls = json.load(f)

    print(f"共 {len(calls)} 条 write_review 记录")
    print(f"测试模型: {MODELS_TO_TEST}")
    print(f"原始模型: {ORIGINAL_MODEL}")
    print(f"{'='*60}")

    # 存储所有结果
    all_results = []

    for idx, call in enumerate(calls):
        call_id = call["id"]
        created_at = call["created_at"]

        # 解析 prompt
        system_content, human_content = parse_langchain_prompt(call["prompt"])
        original_output = call.get("output", "")

        print(f"\n[{idx+1}/{len(calls)}] {call_id[:8]}... ({created_at})")
        print(f"  System: {len(system_content)} chars, Human: {len(human_content)} chars")
        print(f"  原始 {ORIGINAL_MODEL} output: {len(original_output)} chars, "
              f"tokens: {call.get('completion_tokens', '?')}")

        # 构建结果行
        # 原始模型的键名统一用下划线版本
        original_key = ORIGINAL_MODEL.replace("-", "_").replace("/", "_")
        result = {
            "index": idx + 1,
            "id": call_id,
            "created_at": created_at,
            "system_prompt_length": len(system_content),
            "human_prompt_length": len(human_content),
            "prompt_total_chars": len(call["prompt"]),
            f"{original_key}_output": original_output,
            f"{original_key}_output_length": len(original_output),
            f"{original_key}_completion_tokens": call.get("completion_tokens", 0),
            f"{original_key}_total_tokens": call.get("total_tokens", 0),
            f"{original_key}_latency_ms": call.get("latency_ms", 0),
        }

        # 用每个模型生成
        for model_name in MODELS_TO_TEST:
            short_name = model_name.replace("-", "_").replace("/", "_")
            print(f"  调用 {model_name}...", end=" ", flush=True)

            resp = call_model(model_name, system_content, human_content)

            result[f"{short_name}_output"] = resp["content"]
            result[f"{short_name}_output_length"] = len(resp["content"])
            result[f"{short_name}_prompt_tokens"] = resp["prompt_tokens"]
            result[f"{short_name}_completion_tokens"] = resp["completion_tokens"]
            result[f"{short_name}_total_tokens"] = resp["total_tokens"]
            result[f"{short_name}_latency_ms"] = resp["latency_ms"]
            result[f"{short_name}_error"] = resp["error"] or ""

            if resp["error"]:
                print(f"❌ 错误: {resp['error'][:100]}")
            else:
                print(f"✅ {resp['completion_tokens']} tokens, "
                      f"output: {len(resp['content'])} chars, "
                      f"{resp['latency_ms']}ms")

            # 请求间隔，避免限流
            if idx < len(calls) - 1 or model_name != MODELS_TO_TEST[-1]:
                time.sleep(DELAY_BETWEEN_CALLS)

        all_results.append(result)

        # 增量保存：每个 prompt 跑完后立即存 JSON 和 CSV
        _save_json(all_results)
        _save_csv(all_results)

    # ======================== 最终汇总 ========================
    _print_summary(all_results)


def _save_csv(results: list):
    """保存 CSV 对比表格"""
    csv_path = OUTPUT_CSV
    print(f"\n保存 CSV: {csv_path}")

    # CSV 列：序号 + prompt信息 + 每个模型的output
    short_names = [m.replace("-", "_").replace("/", "_") for m in MODELS_TO_TEST]
    original_key = ORIGINAL_MODEL.replace("-", "_").replace("/", "_")

    fieldnames = [
        "序号", "ID", "创建时间",
        "System_Prompt长度", "Human_Prompt长度",
        f"{original_key}_output_length", f"{original_key}_completion_tokens", f"{original_key}_latency_ms",
        f"{original_key}_output",
    ]

    for sn in short_names:
        fieldnames += [
            f"{sn}_output_length",
            f"{sn}_completion_tokens",
            f"{sn}_latency_ms",
            f"{sn}_output",
        ]

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            row = {
                "序号": r["index"],
                "ID": r["id"],
                "创建时间": r["created_at"],
                "System_Prompt长度": r["system_prompt_length"],
                "Human_Prompt长度": r["human_prompt_length"],
                f"{original_key}_output_length": r[f"{original_key}_output_length"],
                f"{original_key}_completion_tokens": r[f"{original_key}_completion_tokens"],
                f"{original_key}_latency_ms": r[f"{original_key}_latency_ms"],
                f"{original_key}_output": r[f"{original_key}_output"],
            }
            for sn in short_names:
                row[f"{sn}_output_length"] = r[f"{sn}_output_length"]
                row[f"{sn}_completion_tokens"] = r[f"{sn}_completion_tokens"]
                row[f"{sn}_latency_ms"] = r[f"{sn}_latency_ms"]
                row[f"{sn}_output"] = r[f"{sn}_output"]
            writer.writerow(row)

    file_size = os.path.getsize(csv_path)
    print(f"  CSV 大小: {file_size:,} bytes")


def _save_json(results: list):
    """保存 JSON 完整对比数据"""
    json_path = OUTPUT_JSON
    print(f"保存 JSON: {json_path}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(json_path)
    print(f"  JSON 大小: {file_size:,} bytes")


def _print_summary(results: list):
    """打印汇总对比"""
    short_names = [m.replace("-", "_").replace("/", "_") for m in MODELS_TO_TEST]
    original_key = ORIGINAL_MODEL.replace("-", "_").replace("/", "_")

    print(f"\n{'='*80}")
    print(f"汇总对比: {ORIGINAL_MODEL} vs {' vs '.join(MODELS_TO_TEST)}")
    print(f"{'='*80}")

    # 计算每个模型的总和
    models_keys = [original_key] + short_names
    summaries = {}

    for key in models_keys:
        total_chars = sum(r[f"{key}_output_length"] for r in results)
        total_tokens = sum(r.get(f"{key}_completion_tokens", 0) for r in results)
        total_latency = sum(r.get(f"{key}_latency_ms", 0) for r in results)
        errors = sum(1 for r in results if r.get(f"{key}_error", ""))
        summaries[key] = {
            "total_chars": total_chars,
            "total_tokens": total_tokens,
            "total_latency": total_latency,
            "errors": errors,
            "avg_chars": total_chars // len(results),
            "avg_tokens": total_tokens // len(results),
            "avg_latency": total_latency // len(results),
        }

    # 打印表头
    model_labels = {
        original_key: f"{ORIGINAL_MODEL} (原始)",
    }
    for i, sn in enumerate(short_names):
        model_labels[sn] = f"{MODELS_TO_TEST[i]}"

    print(f"{'指标':<20} {' | '.join(f'{model_labels[k]:<35}' for k in models_keys)}")
    print("-" * (20 + 38 * len(models_keys)))

    metrics = [
        ("总输出字符数", "total_chars"),
        ("平均输出字符数", "avg_chars"),
        ("总 Completion Tokens", "total_tokens"),
        ("平均 Completion Tokens", "avg_tokens"),
        ("总耗时(ms)", "total_latency"),
        ("平均耗时(ms)", "avg_latency"),
        ("错误数", "errors"),
    ]

    for label, metric in metrics:
        values = [str(summaries[k][metric]) for k in models_keys]
        print(f"{label:<20} {' | '.join(f'{v:<35}' for v in values)}")


if __name__ == "__main__":
    main()
