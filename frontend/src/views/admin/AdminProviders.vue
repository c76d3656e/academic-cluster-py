<script setup lang="ts">
import { shallowRef, ref, computed, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { adminApi, type ProviderInfo, type SourceConfigItem } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'

const { t } = useI18n()

type ProviderTab = 'llm' | 'embedding' | 'rerank'
type AdminTab = ProviderTab | 'source'

const activeTab = shallowRef<AdminTab>('llm')
const providers = ref<ProviderInfo[]>([])
const sources = ref<SourceConfigItem[]>([])
const isLoading = shallowRef(true)
const isReloading = shallowRef(false)
const testingId = shallowRef<string | null>(null)

const showDialog = shallowRef(false)
const isSaving = shallowRef(false)
const editingId = shallowRef<string | null>(null)
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

const showSourceDialog = shallowRef(false)
const sourceDialogMode = shallowRef<'replace' | 'append'>('replace')
const isSourceSaving = shallowRef(false)
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
  sourceDialogMode.value = 'replace'
  sourceForm.value = {
    key: source.key,
    label: source.label,
    value: '',
    is_secret: source.is_secret,
    description: source.description,
  }
  showSourceDialog.value = true
}

function openSourceAppend(source: SourceConfigItem) {
  sourceDialogMode.value = 'append'
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
  if (!confirm(t('admin.deleteProviderConfirm', { name: p.display_name }))) return
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
    if (sourceDialogMode.value === 'append') {
      await adminApi.appendSourceConfig(sourceForm.value.key, {
        value: sourceForm.value.value,
      })
    } else {
      await adminApi.updateSourceConfig(sourceForm.value.key, {
        value: sourceForm.value.value,
        is_enabled: true,
      })
    }
    showSourceDialog.value = false
    await loadSources()
  } catch {
    // ignore
  } finally {
    isSourceSaving.value = false
  }
}

async function handleSourceClear(source: SourceConfigItem) {
  if (!confirm(t('admin.clearConfirm', { label: source.label }))) return
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
  return '$' + parseFloat(v.toFixed(6))
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

function sourceDialogTitle(): string {
  return sourceDialogMode.value === 'append'
    ? t('admin.appendTitle', { label: sourceForm.value.label })
    : t('admin.editSourceTitle', { label: sourceForm.value.label })
}

function sourceDialogHelp(): string {
  if (sourceDialogMode.value === 'append') {
    return t('admin.appendHelp')
  }
  return t('admin.editSourceHelp')
}

onMounted(loadData)
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.providerManagement') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.providerDesc') }}</p>
      </div>
      <div v-if="isProviderTab" class="flex gap-2 shrink-0">
        <Button variant="outline" size="sm" :disabled="isReloading" @click="handleReload">
          {{ isReloading ? t('common.reloading') : t('common.reload') }}
        </Button>
        <Button size="sm" @click="openCreate">{{ t('admin.newProvider') }}</Button>
      </div>
    </div>

    <div class="flex gap-1 mb-6 border-b border-border overflow-x-auto">
      <button
        v-for="tab in (['llm', 'embedding', 'rerank', 'source'] as const)"
        :key="tab"
        class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px shrink-0"
        :class="activeTab === tab
          ? 'border-foreground text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground'"
        @click="activeTab = tab"
      >
        {{ providerTabLabel(tab) }}
      </button>
    </div>

    <div v-if="isLoading" class="text-center py-12 text-muted-foreground text-sm">{{ t('common.loading') }}</div>

    <Card v-else-if="isProviderTab" class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0 overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.thName') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden md:table-cell">{{ t('admin.thModel') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden lg:table-cell">{{ t('admin.thApiKey') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal hidden lg:table-cell">{{ t('admin.thInputPrice') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal hidden lg:table-cell">{{ t('admin.thOutputPrice') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.thStatus') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden sm:table-cell">{{ t('admin.thHealth') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredProviders.length === 0">
              <td colspan="8" class="text-center py-12 text-muted-foreground">
                {{ t('admin.noProvider', { type: providerTabLabel(activeTab) }) }}
              </td>
            </tr>
            <tr
              v-for="p in filteredProviders"
              :key="p.id"
              class="border-b border-border last:border-0 hover:bg-muted/50 transition-colors"
            >
              <td class="py-3 px-4 font-medium">{{ p.display_name }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs hidden md:table-cell">{{ p.model || '-' }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs hidden lg:table-cell">{{ p.api_key_hint || '-' }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs hidden lg:table-cell">{{ formatPrice(p.input_price_per_m) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs hidden lg:table-cell">{{ formatPrice(p.output_price_per_m) }}</td>
              <td class="py-3 px-4">
                <button class="cursor-pointer" @click="handleToggle(p)">
                  <Badge :variant="p.is_enabled ? 'default' : 'outline'" class="text-[0.65rem]">
                    {{ p.is_enabled ? t('common.enabled') : t('common.disabled') }}
                  </Badge>
                </button>
              </td>
              <td class="py-3 px-4 hidden sm:table-cell">
                <Badge :variant="getHealthVariant(p.health_status)" class="text-[0.65rem]">
                  {{ p.health_status }}
                </Badge>
              </td>
              <td class="py-3 px-4">
                <div class="flex gap-1 flex-wrap">
                  <Button variant="ghost" size="sm" class="text-xs" @click="openEdit(p)">{{ t('common.edit') }}</Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs"
                    :disabled="testingId === p.id"
                    @click="handleTest(p)"
                  >
                    {{ testingId === p.id ? t('common.testing') : t('common.test') }}
                  </Button>
                  <Button variant="ghost" size="sm" class="text-xs text-destructive" @click="handleDelete(p)">
                    {{ t('common.delete') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0 overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.thSource') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden lg:table-cell">{{ t('admin.thCurrentValue') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden sm:table-cell">{{ t('admin.thOrigin') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden sm:table-cell">{{ t('admin.thStatus') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal hidden md:table-cell">{{ t('admin.thUpdated') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.thActions') }}</th>
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
              <td class="py-3 px-4 hidden lg:table-cell">
                <div class="text-muted-foreground font-mono text-xs">{{ source.value || '-' }}</div>
                <div v-if="source.key_count > 0" class="text-[0.65rem] text-muted-foreground mt-1">
                  {{ source.supports_multiple ? t('admin.keysCount', { count: source.key_count }) : t('admin.itemCount', { count: source.key_count }) }}
                </div>
              </td>
              <td class="py-3 px-4 hidden sm:table-cell">
                <Badge variant="outline" class="text-[0.65rem]">{{ source.value_source }}</Badge>
              </td>
              <td class="py-3 px-4 hidden sm:table-cell">
                <Badge :variant="sourceBadgeVariant(source)" class="text-[0.65rem]">
                  {{ sourceStatus(source) }}
                </Badge>
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs hidden md:table-cell">
                {{ source.updated_at ? new Date(source.updated_at).toLocaleString() : '-' }}
              </td>
              <td class="py-3 px-4">
                <div class="flex gap-1 flex-wrap">
                  <Button
                    v-if="source.supports_multiple"
                    variant="ghost"
                    size="sm"
                    class="text-xs"
                    @click="openSourceAppend(source)"
                  >
                    {{ t('admin.addKey') }}
                  </Button>
                  <Button variant="ghost" size="sm" class="text-xs" @click="openSourceEdit(source)">{{ t('common.edit') }}</Button>
                  <Button variant="ghost" size="sm" class="text-xs text-destructive" @click="handleSourceClear(source)">
                    {{ t('common.clear') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>

    <Dialog v-model:open="showDialog">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ editingId ? t('admin.editProvider') : t('admin.createProvider') }}</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label class="text-sm">{{ t('admin.providerName') }}</Label>
              <Input v-model="form.display_name" :placeholder="t('admin.providerNamePlaceholder')" class="mt-1" />
            </div>
            <div>
              <Label class="text-sm">{{ t('admin.providerModel') }}</Label>
              <Input v-model="form.model" :placeholder="t('admin.providerModelPlaceholder')" class="mt-1" />
            </div>
          </div>
          <div>
            <Label class="text-sm">{{ t('admin.baseUrl') }}</Label>
            <Input v-model="form.base_url" :placeholder="t('admin.baseUrlPlaceholder')" class="mt-1" />
          </div>
          <div>
            <Label class="text-sm">{{ t('admin.apiKey') }} {{ editingId ? t('admin.apiKeyKeep') : '' }}</Label>
            <Input v-model="form.api_key" type="password" :placeholder="t('admin.apiKeyPlaceholder')" class="mt-1" />
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label class="text-sm">{{ t('admin.priority') }}</Label>
              <Input v-model.number="form.priority" type="number" class="mt-1" />
            </div>
            <div>
              <Label class="text-sm">{{ t('admin.rpmLimit') }}</Label>
              <Input v-model.number="form.rpm_limit" type="number" class="mt-1" />
            </div>
          </div>
          <div class="border-t border-border pt-4">
            <Label class="text-sm font-medium">{{ t('admin.modelPricing') }}</Label>
            <p class="text-[0.65rem] text-muted-foreground mb-3">{{ t('admin.pricingNote') }}</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <Label class="text-xs text-muted-foreground">{{ t('admin.inputPrice') }}</Label>
                <Input v-model.number="form.input_price_per_m" type="number" step="0.000001" min="0" placeholder="0.00" class="mt-1" />
              </div>
              <div>
                <Label class="text-xs text-muted-foreground">{{ t('admin.outputPrice') }}</Label>
                <Input v-model.number="form.output_price_per_m" type="number" step="0.000001" min="0" placeholder="0.00" class="mt-1" />
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" @click="showDialog = false">{{ t('common.cancel') }}</Button>
          <Button size="sm" :disabled="isSaving || !form.display_name || !form.base_url" @click="handleSave">
            {{ isSaving ? t('common.saving') : (editingId ? t('common.save') : t('common.create')) }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="showSourceDialog">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ sourceDialogTitle() }}</DialogTitle>
        </DialogHeader>
        <p class="text-sm text-muted-foreground">{{ sourceForm.description }}</p>
        <div>
          <Label class="text-sm">{{ t('admin.value') }}</Label>
          <Input
            v-model="sourceForm.value"
            :type="sourceForm.is_secret ? 'password' : 'text'"
            :placeholder="sourceDialogMode === 'append' ? t('admin.appendPlaceholder') : (sourceForm.is_secret ? t('admin.editSecretPlaceholder') : t('admin.editPlaceholder'))"
            class="mt-1"
          />
          <p class="text-xs text-muted-foreground mt-2">{{ sourceDialogHelp() }}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" @click="showSourceDialog = false">{{ t('common.cancel') }}</Button>
          <Button size="sm" :disabled="isSourceSaving" @click="handleSourceSave">
            {{ isSourceSaving ? t('common.saving') : t('common.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
