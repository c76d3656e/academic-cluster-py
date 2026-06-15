<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi, type ProviderInfo } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const activeTab = ref<'llm' | 'embedding' | 'rerank'>('llm')
const providers = ref<ProviderInfo[]>([])
const isLoading = ref(true)
const isReloading = ref(false)
const testingId = ref<string | null>(null)

// Dialog state
const showDialog = ref(false)
const isSaving = ref(false)
const editingId = ref<string | null>(null)
const form = ref({
  display_name: '',
  base_url: '',
  model: '',
  api_key: '',
  priority: 100,
  rpm_limit: 10,
  input_price_per_m: 0,
  output_price_per_m: 0,
})

const filteredProviders = computed(() =>
  providers.value.filter(p => p.kind === activeTab.value)
)

function openCreate() {
  editingId.value = null
  form.value = { display_name: '', base_url: '', model: '', api_key: '', priority: 100, rpm_limit: 10, input_price_per_m: 0, output_price_per_m: 0 }
  showDialog.value = true
}

function openEdit(p: ProviderInfo) {
  editingId.value = p.id
  form.value = {
    display_name: p.display_name,
    base_url: p.base_url,
    model: p.model || '',
    api_key: '',
    priority: p.priority,
    rpm_limit: p.rpm_limit,
    input_price_per_m: p.input_price_per_m,
    output_price_per_m: p.output_price_per_m,
  }
  showDialog.value = true
}

async function loadProviders() {
  isLoading.value = true
  try {
    const res = await adminApi.listProviders()
    providers.value = res.providers
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

async function handleToggle(p: ProviderInfo) {
  try {
    const res = await adminApi.toggleProvider(p.id)
    p.is_enabled = res.is_enabled
  } catch {
    // ignore
  }
}

async function handleTest(p: ProviderInfo) {
  testingId.value = p.id
  try {
    const res = await adminApi.testProvider(p.id)
    p.health_status = res.healthy ? 'healthy' : 'error'
    p.last_error = res.healthy ? null : res.message
  } catch {
    p.health_status = 'error'
  } finally {
    testingId.value = null
  }
}

async function handleDelete(p: ProviderInfo) {
  if (!confirm(`确定删除 Provider "${p.display_name}"？`)) return
  try {
    await adminApi.deleteProvider(p.id)
    providers.value = providers.value.filter(x => x.id !== p.id)
  } catch {
    // ignore
  }
}

async function handleReload() {
  isReloading.value = true
  try {
    const res = await adminApi.reloadProviders()
    alert(res.message)
    await loadProviders()
  } catch {
    // ignore
  } finally {
    isReloading.value = false
  }
}

async function handleSave() {
  isSaving.value = true
  try {
    const payload = {
      display_name: form.value.display_name,
      base_url: form.value.base_url,
      model: form.value.model || undefined,
      priority: form.value.priority,
      rpm_limit: form.value.rpm_limit,
      input_price_per_m: form.value.input_price_per_m,
      output_price_per_m: form.value.output_price_per_m,
    }

    if (editingId.value) {
      // Update
      const apiPayload: Record<string, unknown> = { ...payload }
      if (form.value.api_key) apiPayload.api_key = form.value.api_key
      await adminApi.updateProvider(editingId.value, apiPayload)
    } else {
      // Create
      await adminApi.createProvider({
        kind: activeTab.value,
        ...payload,
        api_key: form.value.api_key || undefined,
      })
    }
    showDialog.value = false
    await loadProviders()
  } catch {
    // ignore
  } finally {
    isSaving.value = false
  }
}

function getHealthVariant(status: string): 'default' | 'destructive' | 'outline' {
  if (status === 'healthy') return 'default'
  if (status === 'error' || status === 'unhealthy') return 'destructive'
  return 'outline'
}

function formatPrice(v: number): string {
  if (v === 0) return '-'
  return '$' + v.toFixed(2)
}

onMounted(loadProviders)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">Provider 管理</h2>
        <p class="text-sm text-muted-foreground mt-1">管理 LLM、Embedding 和 Rerank 服务及定价</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" :disabled="isReloading" @click="handleReload">
          {{ isReloading ? '重载中...' : '热重载' }}
        </Button>
        <Button size="sm" @click="openCreate">新增 Provider</Button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b border-border">
      <button
        v-for="tab in (['llm', 'embedding', 'rerank'] as const)"
        :key="tab"
        @click="activeTab = tab"
        class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px"
        :class="activeTab === tab
          ? 'border-foreground text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground'"
      >
        {{ tab === 'llm' ? 'LLM' : tab === 'embedding' ? 'Embedding' : 'Rerank' }}
      </button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="text-center py-12 text-muted-foreground text-sm">加载中...</div>

    <!-- Provider List -->
    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">名称</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">模型</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">API Key</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输入 $/M</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输出 $/M</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">状态</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">健康</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredProviders.length === 0">
              <td colspan="8" class="text-center py-12 text-muted-foreground">
                暂无 {{ activeTab === 'llm' ? 'LLM' : activeTab === 'embedding' ? 'Embedding' : 'Rerank' }} Provider
              </td>
            </tr>
            <tr
              v-for="p in filteredProviders"
              :key="p.id"
              class="border-b border-border last:border-0 hover:bg-muted/50 transition-colors"
            >
              <td class="py-3 px-4 font-medium">{{ p.display_name }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs">{{ p.model || '-' }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs">{{ p.api_key_hint || '-' }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatPrice(p.input_price_per_m) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatPrice(p.output_price_per_m) }}</td>
              <td class="py-3 px-4">
                <button @click="handleToggle(p)" class="cursor-pointer">
                  <Badge :variant="p.is_enabled ? 'default' : 'outline'" class="text-[0.65rem]">
                    {{ p.is_enabled ? '启用' : '禁用' }}
                  </Badge>
                </button>
              </td>
              <td class="py-3 px-4">
                <Badge :variant="getHealthVariant(p.health_status)" class="text-[0.65rem]">
                  {{ p.health_status }}
                </Badge>
              </td>
              <td class="py-3 px-4">
                <div class="flex gap-1">
                  <Button variant="ghost" size="sm" class="text-xs" @click="openEdit(p)">编辑</Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs"
                    :disabled="testingId === p.id"
                    @click="handleTest(p)"
                  >
                    {{ testingId === p.id ? '测试中...' : '测试' }}
                  </Button>
                  <Button variant="ghost" size="sm" class="text-xs text-destructive" @click="handleDelete(p)">
                    删除
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>

    <!-- Create/Edit Dialog -->
    <div v-if="showDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showDialog = false">
      <div class="bg-background rounded-lg shadow-lg w-full max-w-lg p-6 border border-border">
        <h3 class="text-lg font-medium mb-4">{{ editingId ? '编辑 Provider' : '新增 Provider' }}</h3>
        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <Label class="text-sm">名称</Label>
              <Input v-model="form.display_name" placeholder="如 SiliconFlow" class="mt-1" />
            </div>
            <div>
              <Label class="text-sm">模型</Label>
              <Input v-model="form.model" placeholder="deepseek-v3" class="mt-1" />
            </div>
          </div>
          <div>
            <Label class="text-sm">Base URL</Label>
            <Input v-model="form.base_url" placeholder="https://api.siliconflow.cn/v1" class="mt-1" />
          </div>
          <div>
            <Label class="text-sm">API Key {{ editingId ? '(留空不修改)' : '' }}</Label>
            <Input v-model="form.api_key" type="password" placeholder="sk-..." class="mt-1" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <Label class="text-sm">优先级</Label>
              <Input v-model.number="form.priority" type="number" class="mt-1" />
            </div>
            <div>
              <Label class="text-sm">RPM 限制</Label>
              <Input v-model.number="form.rpm_limit" type="number" class="mt-1" />
            </div>
          </div>
          <div class="border-t border-border pt-4">
            <Label class="text-sm font-medium">模型定价 ($/M tokens)</Label>
            <p class="text-[0.65rem] text-muted-foreground mb-3">修改后新调用立即按新价格计费，历史记录不变</p>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <Label class="text-xs text-muted-foreground">输入价格</Label>
                <Input v-model.number="form.input_price_per_m" type="number" step="0.01" min="0" placeholder="0.00" class="mt-1" />
              </div>
              <div>
                <Label class="text-xs text-muted-foreground">输出价格</Label>
                <Input v-model.number="form.output_price_per_m" type="number" step="0.01" min="0" placeholder="0.00" class="mt-1" />
              </div>
            </div>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <Button variant="outline" size="sm" @click="showDialog = false">取消</Button>
          <Button size="sm" :disabled="isSaving || !form.display_name || !form.base_url" @click="handleSave">
            {{ isSaving ? '保存中...' : (editingId ? '保存' : '创建') }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
