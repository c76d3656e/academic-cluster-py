<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi, type PipelineConfigItem } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const configs = ref<PipelineConfigItem[]>([])
const isLoading = ref(true)
const isSaving = ref(false)
const editingKey = ref<string | null>(null)
const editValue = ref('')
const isResetting = ref(false)

const groupedConfigs = computed(() => {
  const groups: Record<string, PipelineConfigItem[]> = {}
  for (const c of configs.value) {
    const g = c.group || 'general'
    if (!groups[g]) groups[g] = []
    groups[g].push(c)
  }
  return groups
})

const groupLabels: Record<string, string> = {
  '搜索': '搜索阶段',
  '过滤': '过滤阶段',
  '嵌入': '嵌入阶段',
  '重排序': '重排序阶段',
  '聚类': '聚类阶段',
  '写作': '写作阶段',
}

const groupIcons: Record<string, string> = {
  '搜索': '🔍',
  '过滤': '🔽',
  '嵌入': '📐',
  '重排序': '📊',
  '聚类': '🧩',
  '写作': '✍️',
}

async function loadConfigs() {
  isLoading.value = true
  try {
    configs.value = await adminApi.getPipelineConfigs()
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

function startEdit(item: PipelineConfigItem) {
  editingKey.value = item.key
  editValue.value = item.value
}

function cancelEdit() {
  editingKey.value = null
  editValue.value = ''
}

async function saveEdit(key: string) {
  isSaving.value = true
  try {
    await adminApi.updatePipelineConfig(key, editValue.value)
    const item = configs.value.find(c => c.key === key)
    if (item) item.value = editValue.value
    editingKey.value = null
    editValue.value = ''
  } catch {
    // ignore
  } finally {
    isSaving.value = false
  }
}

async function handleReset() {
  if (!confirm('确定重置所有 pipeline 配置为默认值？')) return
  isResetting.value = true
  try {
    await adminApi.resetPipelineConfigs()
    await loadConfigs()
  } catch {
    // ignore
  } finally {
    isResetting.value = false
  }
}

function formatValue(val: string, type: string): string {
  if (type === 'bool') return val === 'true' ? '是' : '否'
  return val
}

function inputType(type: string): string {
  if (type === 'float' || type === 'int') return 'number'
  return 'text'
}

function onInputKeyup(e: KeyboardEvent, key: string) {
  if (e.key === 'Enter') saveEdit(key)
  else if (e.key === 'Escape') cancelEdit()
}

onMounted(loadConfigs)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">Pipeline 配置</h2>
        <p class="text-sm text-muted-foreground mt-1">调整搜索、过滤、聚类、写作等阶段的参数，新 pipeline 运行时生效</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" :disabled="isResetting" @click="handleReset">
          {{ isResetting ? '重置中...' : '重置默认' }}
        </Button>
        <Button size="sm" @click="loadConfigs">刷新</Button>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-12 text-muted-foreground text-sm">加载中...</div>

    <div v-else class="space-y-6">
      <Card
        v-for="(items, group) in groupedConfigs"
        :key="group"
        class="border border-border shadow-[var(--shadow-sm)]"
      >
        <CardContent class="p-6">
          <h3 class="text-base font-medium mb-4">
            {{ groupIcons[group] || '' }} {{ groupLabels[group] || group }}
          </h3>

          <div class="space-y-3">
            <div
              v-for="item in items"
              :key="item.key"
              class="flex items-center gap-4 py-2 border-b border-border last:border-0"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium">{{ item.label }}</span>
                  <code class="text-[0.65rem] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{{ item.key }}</code>
                </div>
                <p class="text-xs text-muted-foreground mt-0.5">{{ item.description }}</p>
              </div>

              <div class="flex items-center gap-2 shrink-0">
                <template v-if="editingKey === item.key">
                  <Input
                    v-model="editValue"
                    :type="inputType(item.type)"
                    :step="item.type === 'float' ? '0.01' : undefined"
                    class="w-40 h-8 text-sm"
                    @keyup="onInputKeyup($event, item.key)"
                  />
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" :disabled="isSaving" @click="saveEdit(item.key)">
                    {{ isSaving ? '...' : '保存' }}
                  </Button>
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" @click="cancelEdit">取消</Button>
                </template>
                <template v-else>
                  <span class="text-sm font-mono bg-muted px-2 py-1 rounded min-w-[3rem] text-center">
                    {{ formatValue(item.value, item.type) }}
                  </span>
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" @click="startEdit(item)">编辑</Button>
                </template>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <div class="mt-6 p-4 bg-muted/50 rounded-lg border border-border">
      <p class="text-xs text-muted-foreground">
        <strong>说明：</strong>修改后的配置在下次启动 pipeline 时生效。当前正在运行的 pipeline 不受影响。
        搜索源列表使用逗号分隔，可选值：semantic_scholar, openalex, crossref, arxiv, pubmed。
        混合图权重之和建议为 1.0。
      </p>
    </div>
  </div>
</template>
