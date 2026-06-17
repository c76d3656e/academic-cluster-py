<script setup lang="ts">
import { shallowRef, ref, computed, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { adminApi, type PipelineConfigItem } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const { t } = useI18n()

const configs = ref<PipelineConfigItem[]>([])
const isLoading = shallowRef(true)
const isSaving = shallowRef(false)
const editingKey = shallowRef<string | null>(null)
const editValue = shallowRef('')
const isResetting = shallowRef(false)

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
  '搜索': 'admin.groupSearch',
  '过滤': 'admin.groupFilter',
  '嵌入': 'admin.groupEmbedding',
  '重排序': 'admin.groupRerank',
  '聚类': 'admin.groupCluster',
  '写作': 'admin.groupWriting',
  'KG 抽取': 'admin.groupKgExtraction',
  '证据卡片': 'admin.groupEvidenceCards',
  '社区记忆': 'admin.groupCommunityMemory',
  '系统': 'admin.groupSystem',
}

const groupIcons: Record<string, string> = {
  '搜索': '🔍',
  '过滤': '🔽',
  '嵌入': '📐',
  '重排序': '📊',
  '聚类': '🧩',
  '写作': '✍️',
}

function getGroupLabel(group: string): string {
  const key = groupLabels[group]
  return key ? t(key) : group
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
  if (!confirm(t('admin.resetConfirm'))) return
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
  if (type === 'bool') return val === 'true' ? t('common.yes') : t('common.no')
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
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.pipelineConfig') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.pipelineConfigDesc') }}</p>
      </div>
      <div class="flex gap-2 shrink-0">
        <Button variant="outline" size="sm" :disabled="isResetting" @click="handleReset">
          {{ isResetting ? t('common.resetting') : t('admin.resetDefault') }}
        </Button>
        <Button size="sm" @click="loadConfigs">{{ t('common.refresh') }}</Button>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-12 text-muted-foreground text-sm">{{ t('common.loading') }}</div>

    <div v-else class="space-y-6">
      <Card
        v-for="(items, group) in groupedConfigs"
        :key="group"
        class="border border-border shadow-[var(--shadow-sm)]"
      >
        <CardContent class="p-6">
          <h3 class="text-base font-medium mb-4">
            {{ groupIcons[group] || '' }} {{ getGroupLabel(group) }}
          </h3>

          <div class="space-y-3">
            <div
              v-for="item in items"
              :key="item.key"
              class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 py-2 border-b border-border last:border-0"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm font-medium">{{ item.label }}</span>
                  <code class="text-[0.65rem] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{{ item.key }}</code>
                </div>
                <p class="text-xs text-muted-foreground mt-0.5">{{ item.description }}</p>
              </div>

              <div class="flex items-center gap-2 shrink-0 flex-wrap justify-start sm:justify-end">
                <template v-if="editingKey === item.key">
                  <Input
                    v-model="editValue"
                    :type="inputType(item.type)"
                    :step="item.type === 'float' ? '0.01' : undefined"
                    class="w-40 h-8 text-sm"
                    @keyup="onInputKeyup($event, item.key)"
                  />
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" :disabled="isSaving" @click="saveEdit(item.key)">
                    {{ isSaving ? '...' : t('common.save') }}
                  </Button>
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" @click="cancelEdit">{{ t('common.cancel') }}</Button>
                </template>
                <template v-else>
                  <span class="text-sm font-mono bg-muted px-2 py-1 rounded min-w-[3rem] text-center">
                    {{ formatValue(item.value, item.type) }}
                  </span>
                  <Button size="sm" variant="ghost" class="text-xs h-7 px-2" @click="startEdit(item)">{{ t('common.edit') }}</Button>
                </template>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <div class="mt-6 p-4 bg-muted/50 rounded-lg border border-border">
      <p class="text-xs text-muted-foreground">
        <strong>{{ t('common.status') }}：</strong>{{ t('admin.configHint') }}
      </p>
    </div>
  </div>
</template>
