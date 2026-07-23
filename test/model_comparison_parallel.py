"""
多模型 Write Review 对比脚本（全并发版）
----------------------------------------
20 条 prompt × 2 模型 = 40 个 API 调用一次性并发发出。
"""
import json
import csv
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from litellm import completion

# ======================== 配置 ========================
API_BASE = "https://ai.gitee.com/v1"
API_KEY = os.environ.get("GITEE_AI_API_KEY")
if not API_KEY:
    raise RuntimeError("GITEE_AI_API_KEY is required")
MODELS_TO_TEST = ["glm-4-9b-chat", "internlm3-8b-instruct"]
ORIGINAL_MODEL = "qwen3-8b"
ORIGINAL_KEY = "qwen3_8b"
MAX_TOKENS = 4096
MAX_WORKERS = 40  # 全部并发

INPUT_JSON = os.path.join(os.path.dirname(__file__), "write_review_final.json")
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "model_comparison.csv")
OUTPUT_JSON = os.path.join(os.path.dirname(__file__), "model_comparison.json")


# ======================== Prompt 解析 ========================
def parse_langchain_prompt(raw_prompt: str) -> tuple[str, str]:
    sys_start = raw_prompt.find("SystemMessage(content='")
    system_content = ""
    human_content = ""

    if sys_start != -1:
        sys_start += len("SystemMessage(content='")
        sys_end = raw_prompt.find("', additional_kwargs={}", sys_start)
        if sys_end != -1:
            system_content = raw_prompt[sys_start:sys_end]
        else:
            system_content = raw_prompt[sys_start:]

    human_start = raw_prompt.find("HumanMessage(content='")
    if human_start != -1:
        human_start += len("HumanMessage(content='")
        human_end = raw_prompt.rfind("', additional_kwargs={}, response_metadata={})]")
        if human_end != -1:
            human_content = raw_prompt[human_start:human_end]
        else:
            human_content = raw_prompt[human_start:]

    system_content = _unescape(system_content)
    human_content = _unescape(human_content)
    return system_content, human_content


def _unescape(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


# ======================== 单次 LLM 调用 ========================
def call_model(model_name: str, system_content: str, user_content: str,
               max_tokens: int = MAX_TOKENS, retries: int = 3) -> dict:
    messages = []
    if system_content and system_content.strip():
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": user_content})

    litellm_model = f"openai/{model_name}"

    for attempt in range(retries):
        start = time.time()
        try:
            resp = completion(model=litellm_model, messages=messages,
                              api_base=API_BASE, api_key=API_KEY,
                              max_tokens=max_tokens, timeout=300)
            elapsed = int((time.time() - start) * 1000)
            return {
                "content": resp.choices[0].message.content,
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
                "model": resp.model, "error": None, "latency_ms": elapsed,
            }
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return {
                    "content": "", "prompt_tokens": 0, "completion_tokens": 0,
                    "total_tokens": 0, "model": model_name,
                    "error": str(e)[:500], "latency_ms": int((time.time() - start) * 1000),
                }


# ======================== 单条 prompt 的任务 ========================
def process_one_call(idx: int, call: dict):
    """处理一条 prompt：解析 + 调 2 个模型（内部并发）"""
    call_id = call["id"]
    created_at = call["created_at"]
    system_content, human_content = parse_langchain_prompt(call["prompt"])
    original_output = call.get("output", "")

    result = {
        "index": idx + 1, "id": call_id, "created_at": created_at,
        "system_prompt_length": len(system_content),
        "human_prompt_length": len(human_content),
        "prompt_total_chars": len(call["prompt"]),
        f"{ORIGINAL_KEY}_output": original_output,
        f"{ORIGINAL_KEY}_output_length": len(original_output),
        f"{ORIGINAL_KEY}_completion_tokens": call.get("completion_tokens", 0),
        f"{ORIGINAL_KEY}_total_tokens": call.get("total_tokens", 0),
        f"{ORIGINAL_KEY}_latency_ms": call.get("latency_ms", 0),
    }

    # 每个 prompt 内部并发调用 2 个模型
    with ThreadPoolExecutor(max_workers=2) as inner_pool:
        futures = {}
        for model_name in MODELS_TO_TEST:
            f = inner_pool.submit(call_model, model_name, system_content, human_content)
            futures[f] = model_name

        for f in as_completed(futures):
            model_name = futures[f]
            short_name = model_name.replace("-", "_").replace("/", "_")
            resp = f.result()
            result[f"{short_name}_output"] = resp["content"]
            result[f"{short_name}_output_length"] = len(resp["content"])
            result[f"{short_name}_prompt_tokens"] = resp["prompt_tokens"]
            result[f"{short_name}_completion_tokens"] = resp["completion_tokens"]
            result[f"{short_name}_total_tokens"] = resp["total_tokens"]
            result[f"{short_name}_latency_ms"] = resp["latency_ms"]
            result[f"{short_name}_error"] = resp["error"] or ""
            status = "❌" if resp["error"] else "✅"
            print(f"  [{idx+1:2d}/20] {call_id[:8]} | {model_name:<30} {status} "
                  f"tok={resp['completion_tokens']} out={len(resp['content'])}ch "
                  f"lat={resp['latency_ms']}ms", flush=True)

    return result


# ======================== CSV 保存 ========================
def save_csv(results: list):
    csv_path = OUTPUT_CSV
    short_names = [m.replace("-", "_").replace("/", "_") for m in MODELS_TO_TEST]

    fieldnames = ["序号", "ID", "创建时间", "System_Prompt长度", "Human_Prompt长度",
                  f"{ORIGINAL_KEY}_output_length", f"{ORIGINAL_KEY}_completion_tokens", f"{ORIGINAL_KEY}_latency_ms",
                  f"{ORIGINAL_KEY}_output"]
    for sn in short_names:
        fieldnames += [f"{sn}_output_length", f"{sn}_completion_tokens", f"{sn}_latency_ms", f"{sn}_output"]

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: x["index"]):
            row = {
                "序号": r["index"], "ID": r["id"], "创建时间": r["created_at"],
                "System_Prompt长度": r["system_prompt_length"], "Human_Prompt长度": r["human_prompt_length"],
                f"{ORIGINAL_KEY}_output_length": r[f"{ORIGINAL_KEY}_output_length"],
                f"{ORIGINAL_KEY}_completion_tokens": r[f"{ORIGINAL_KEY}_completion_tokens"],
                f"{ORIGINAL_KEY}_latency_ms": r[f"{ORIGINAL_KEY}_latency_ms"],
                f"{ORIGINAL_KEY}_output": r[f"{ORIGINAL_KEY}_output"],
            }
            for sn in short_names:
                row[f"{sn}_output_length"] = r[f"{sn}_output_length"]
                row[f"{sn}_completion_tokens"] = r[f"{sn}_completion_tokens"]
                row[f"{sn}_latency_ms"] = r[f"{sn}_latency_ms"]
                row[f"{sn}_output"] = r[f"{sn}_output"]
            writer.writerow(row)
    print(f"CSV 已保存: {csv_path} ({os.path.getsize(csv_path):,} bytes)")


# ======================== 主流程 ========================
def main():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        calls = json.load(f)

    print(f"全并发模式: {len(calls)} prompts × {len(MODELS_TO_TEST)} models = "
          f"{len(calls) * len(MODELS_TO_TEST)} 并发调用")
    print(f"模型: {MODELS_TO_TEST}")
    print(f"原始模型: {ORIGINAL_MODEL}")
    print(f"{'='*80}")

    t_start = time.time()

    # 一次性全并发提交 20 条 prompt
    all_results = [None] * len(calls)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_one_call, i, call): i for i, call in enumerate(calls)}
        for f in as_completed(futures):
            i = futures[f]
            all_results[i] = f.result()

    total_elapsed = int((time.time() - t_start) * 1000)
    print(f"\n{'='*80}")
    print(f"全部完成！总耗时: {total_elapsed/1000:.1f}s ({total_elapsed}ms)")

    save_csv(all_results)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted(all_results, key=lambda x: x["index"]), f, ensure_ascii=False, indent=2)

    # 汇总
    short_names = [m.replace("-", "_").replace("/", "_") for m in MODELS_TO_TEST]
    all_keys = [ORIGINAL_KEY] + short_names
    labels = {ORIGINAL_KEY: f"{ORIGINAL_MODEL}(原始)"}
    for i, sn in enumerate(short_names):
        labels[sn] = MODELS_TO_TEST[i]

    print(f"\n{'指标':<22}", end="")
    for k in all_keys:
        print(f" | {labels[k]:<30}", end="")
    print(f"\n{'-'*(22+32*len(all_keys))}")

    for metric, accessor in [("总输出字符", "output_length"), ("总 Tokens", "completion_tokens"),
                               ("平均输出字符", "output_length_avg"), ("错误数", "error")]:
        print(f"{metric:<22}", end="")
        for k in all_keys:
            if accessor == "error":
                val = sum(1 for r in all_results if r.get(f"{k}_error", ""))
            elif accessor.endswith("_avg"):
                vals = [r.get(f"{k}_output_length", 0) for r in all_results if r.get(f"{k}_error", "err") == ""]
                val = sum(vals) // max(len(vals), 1)
            else:
                val = sum(r.get(f"{k}_{accessor}", 0) for r in all_results)
            print(f" | {str(val):<30}", end="")
        print()

    print(f"\n文件已生成: {OUTPUT_CSV}, {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
