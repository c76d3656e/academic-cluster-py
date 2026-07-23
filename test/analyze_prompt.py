import json

with open('write_review_final.json', 'r', encoding='utf-8') as f:
    calls = json.load(f)

# Parse first prompt to understand structure
p = calls[0]['prompt']
print('=== Prompt 0 结构分析 ===')
print(f'总长度: {len(p)}')
print(f'开头: {p[:50]}')

# Find the SystemMessage content
sys_start_marker = "SystemMessage(content='"
sys_start = p.find(sys_start_marker) + len(sys_start_marker)

# Find the end of SystemMessage content
# It ends at: ', additional_kwargs={}, response_metadata={})
sys_end_marker = "', additional_kwargs={}"
sys_end = p.find(sys_end_marker, sys_start)
sys_content = p[sys_start:sys_end]

print(f'\nSystem消息长度: {len(sys_content)}')
print(f'System消息前150字: {sys_content[:150]}')

# Find HumanMessage
human_marker = "HumanMessage(content='"
human_start = p.find(human_marker)
if human_start > 0:
    human_content_start = human_start + len(human_marker)
    human_end_marker = "', additional_kwargs={}, response_metadata={})]"
    human_end = p.rfind(human_end_marker)
    human_content = p[human_content_start:human_end]
    print(f'\nHuman消息长度: {len(human_content)}')
    print(f'Human消息前200字: {human_content[:200]}')
    print(f'Human消息后100字: {human_content[-100:]}')
else:
    print('No HumanMessage found')

# Check unescaping
print('=== 转义检查 ===')
bs = chr(92)
dq = chr(34)
print('包含 \\\\n:', (bs + 'n') in sys_content)
print('包含 \\\":', (bs + dq) in sys_content)
