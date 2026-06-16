<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi, type ProviderInfo, type SourceConfigItem } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type ProviderTab = 'llm' | 'embedding' | 'rerank'
type AdminTab = ProviderTab | 'source'

const activeTab = ref<AdminTab>('llm')
const providers = ref<ProviderInfo[]>([])
const sources = ref<SourceConfigItem[]>([])
const isLoading = ref(true)
const isReloading = ref(false)
const testingId = ref<string | null>(null)

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

const showSourceDialog = ref(false)
const isSourceSaving = ref(false)
const sourceForm = ref({
  key: '',
  label: '',
  value: '',
  is_secret: true,
  description: '',
})

const isProviderTab = computed(() => activeTab.value !== 'source')
const filteredProviders = computed(() =>
  isProviderTab.value
    ? providers.value.filter(p => p.kind === activeTab.value)
    : [],
)

function providerTabLabel(tab: AdminTab): string {
  if (tab === 'llm') return 'LLM'
  if (tab === 'embedding') return 'Embedding'
  if (tab === 'rerank') return 'Rerank'
  return 'Source'
}

function openCreate() {
  if (!isProviderTab.value) return
  editingId.value = null
  form.value = {
    display_name: '',
    base_url: '',
    model: '',
    api_key: '',
    priority: 100,
    rpm_limit: 10,
    input_price_per_m: 0,
    output_price_per_m: 0,
  }
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

function openSourceEdit(source: SourceConfigItem) {
  sourceForm.value = {
    key: source.key,
    label: source.label,
    value: '',
    is_secret: source.is_secret,
    description: source.description,
  }
  showSourceDialog.value = true
}

async function loadData() {
  isLoading.value = true
  try {
    const [providerRes, sourceRes] = await Promise.all([
      adminApi.listProviders(),
      adminApi.getSourceConfigs(),
    ])
    providers.value = providerRes.providers
    sources.value = sourceRes
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

async function loadProviders() {
  const res = await adminApi.listProviders()
  providers.value = res.providers
}

async function loadSources() {
  sources.value = await adminApi.getSourceConfigs()
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
  if (!isProviderTab.value) return
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
      const apiPayload: Record<string, unknown> = { ...payload }
      if (form.value.api_key) apiPayload.api_key = form.value.api_key
      await adminApi.updateProvider(editingId.value, apiPayload)
    } else {
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

async function handleSourceSave() {
  isSourceSaving.value = true
  try {
    await adminApi.updateSourceConfig(sourceForm.value.key, {
      value: sourceForm.value.value,
      is_enabled: true,
    })
    showSourceDialog.value = false
    await loadSources()
  } catch {
    // ignore
  } finally {
    isSourceSaving.value = false
  }
}

async function handleSourceClear(source: SourceConfigItem) {
  if (!confirm(`确定清空 ${source.label}？清空后不会回退到 .env。`)) return
  try {
    await adminApi.deleteSourceConfig(source.key)
    await loadSources()
  } catch {
    // ignore
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

function sourceBadgeVariant(source: SourceConfigItem): 'default' | 'destructive' | 'outline' {
  if (source.is_set) return 'default'
  if (!source.is_enabled && source.value_source === 'db') return 'destructive'
  return 'outline'
}

function sourceStatus(source: SourceConfigItem): string {
  if (source.is_set) return source.value_source === 'db' ? 'DB override' : '.env fallback'
  if (!source.is_enabled && source.value_source === 'db') return 'Cleared'
  return 'Unset'
}

onMounted(loadData)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">Provider 管理</h2>
        <p class="text-sm text-muted-foreground mt-1">管理模型服务、学术搜索源凭据和运行时配置</p>
      </div>
      <div v-if="isProviderTab" class="flex gap-2">
        <Button variant="outline" size="sm" :disabled="isReloading" @click="handleReload">
          {{ isReloading ? '重载中...' : '热重载' }}
        </Button>
        <Button size="sm" @click="openCreate">新增 Provider</Button>
      </div>
    </div>

    <div class="flex gap-1 mb-6 border-b border-border">
      <button
        v-for="tab in (['llm', 'embedding', 'rerank', 'source'] as const)"
        :key="tab"
        @click="activeTab = tab"
        class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px"
        :class="activeTab === tab
          ? 'border-foreground text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground'"
      >
        {{ providerTabLabel(tab) }}
      </button>
    </div>

    <div v-if="isLoading" class="text-center py-12 text-muted-foreground text-sm">加载中...</div>

    <Card v-else-if="isProviderTab" class="border border-border shadow-[var(--shadow-sm)]">
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
                暂无 {{ providerTabLabel(activeTab) }} Provider
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

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">数据源</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">当前值</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">来源</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">状态</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">更新时间</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="source in sources"
              :key="source.key"
              class="border-b border-border last:border-0 hover:bg-muted/50 transition-colors"
            >
              <td class="py-3 px-4">
                <div class="font-medium">{{ source.label }}</div>
                <div class="text-xs text-muted-foreground mt-1 max-w-[36rem]">{{ source.description }}</div>
              </td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs">{{ source.value || '-' }}</td>
              <td class="py-3 px-4">
                <Badge variant="outline" class="text-[0.65rem]">{{ source.value_source }}</Badge>
              </td>
              <td class="py-3 px-4">
                <Badge :variant="sourceBadgeVariant(source)" class="text-[0.65rem]">
                  {{ sourceStatus(source) }}
                </Badge>
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs">
                {{ source.updated_at ? new Date(source.updated_at).toLocaleString() : '-' }}
              </td>
              <td class="py-3 px-4">
                <div class="flex gap-1">
                  <Button variant="ghost" size="sm" class="text-xs" @click="openSourceEdit(source)">编辑</Button>
                  <Button variant="ghost" size="sm" class="text-xs text-destructive" @click="handleSourceClear(source)">
                    清空
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>

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
              <Input v-model="form.model" placeholder="Qwen3-8B" class="mt-1" />
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
            <p class="text-[0.65rem] text-muted-foreground mb-3">修改后新调用立即按新价格计费，历史记录不改变。</p>
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

    <div v-if="showSourceDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showSourceDialog = false">
      <div class="bg-background rounded-lg shadow-lg w-full max-w-lg p-6 border border-border">
        <h3 class="text-lg font-medium mb-1">编辑 {{ sourceForm.label }}</h3>
        <p class="text-sm text-muted-foreground mb-4">{{ sourceForm.description }}</p>
        <div>
          <Label class="text-sm">配置值</Label>
          <Input
            v-model="sourceForm.value"
            :type="sourceForm.is_secret ? 'password' : 'text'"
            :placeholder="sourceForm.is_secret ? '输入新的 API Key' : '输入邮箱地址'"
            class="mt-1"
          />
          <p class="text-xs text-muted-foreground mt-2">保存后将写入数据库并优先生效；留空保存等同清空。</p>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <Button variant="outline" size="sm" @click="showSourceDialog = false">取消</Button>
          <Button size="sm" :disabled="isSourceSaving" @click="handleSourceSave">
            {{ isSourceSaving ? '保存中...' : '保存' }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
