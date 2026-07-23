import os
import time

from litellm import completion

api_key = os.environ.get("GITEE_AI_API_KEY")
if not api_key:
    raise RuntimeError("GITEE_AI_API_KEY is required")

t0 = time.time()
resp = completion(
    model="openai/glm-4-9b-chat",
    messages=[{"role": "user", "content": "用一句话介绍深度学习"}],
    api_base="https://ai.gitee.com/v1",
    api_key=api_key,
    max_tokens=100,
    timeout=30,
)
elapsed = int((time.time() - t0) * 1000)
print(f"Model: {resp.model}")
print(f"Content: {resp.choices[0].message.content[:200]}")
print(f"Tokens: {resp.usage.completion_tokens if resp.usage else 'N/A'}")
print(f"Latency: {elapsed}ms")
print("litellm OK!")
