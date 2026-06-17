<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { useI18n } from '@/i18n'
import { formatCost } from '@/lib/utils'
import { PIPELINE_STAGES } from '@/composables/useProjectProgress'
import type { ConsoleLlmCall } from '@/api/console'

const { t } = useI18n()

const props = defineProps<{
  llmCalls: ConsoleLlmCall[]
  isLoadingCalls: boolean
  selectedLlmNode: string
}>()

const emit = defineEmits<{
  (e: 'update:selectedLlmNode', value: string): void
  (e: 'filter-change'): void
}>()

const recentNodeCalls = computed(() => props.llmCalls.slice(0, 200))

const pipelineStages = PIPELINE_STAGES

function formatCallTime(value: string | null): string {
  if (!value) return ''
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function onFilterChange(e: Event) {
  emit('update:selectedLlmNode', (e.target as HTMLSelectElement).value)
  emit('filter-change')
}
</script>

<template>
  <details class="mt-4 border border-border rounded-xl bg-card overflow-hidden" open>
    <summary class="px-5 py-3 text-sm font-medium cursor-pointer hover:bg-muted/50 transition-colors">
      LLM {{ t('common.log') }} ({{ llmCalls.length }})
    </summary>
    <div class="px-5 pb-4">
      <div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span class="text-muted-foreground">{{ t('common.node') }}</span>
        <select
          :value="selectedLlmNode"
          class="h-8 rounded-md border border-border bg-background px-2 text-xs"
          @change="onFilterChange"
        >
          <option value="">{{ t('admin.recentCallsTitle') }}</option>
          <option v-for="stage in pipelineStages" :key="stage.key" :value="stage.key">
            {{ stage.label }} / {{ stage.key }}
          </option>
        </select>
        <span class="text-muted-foreground">
          {{ t('pipeline.llmFilterHint') }}
        </span>
      </div>
      <div v-if="isLoadingCalls && llmCalls.length === 0" class="text-center py-4 text-sm text-muted-foreground">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="recentNodeCalls.length === 0" class="text-center py-4 text-sm text-muted-foreground">
        {{ t('console.noCallRecords') }}
      </div>
      <div v-else class="max-h-96 overflow-auto">
        <table class="w-full text-xs">
          <thead class="text-muted-foreground border-b border-border">
            <tr>
              <th class="py-2 pr-3 text-left font-medium">{{ t('common.time') }}</th>
              <th class="py-2 pr-3 text-left font-medium">{{ t('common.node') }}</th>
              <th class="py-2 pr-3 text-left font-medium">{{ t('common.model') }}</th>
              <th class="py-2 pr-3 text-left font-medium">{{ t('common.status') }}</th>
              <th class="py-2 pr-3 text-left font-medium">{{ t('common.log') }}</th>
              <th class="py-2 pr-3 text-right font-medium">{{ t('common.tokens') }}</th>
              <th class="py-2 pr-3 text-right font-medium">{{ t('common.latency') }}</th>
              <th class="py-2 text-right font-medium">{{ t('common.cost') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="call in recentNodeCalls" :key="call.id" class="border-b border-border/50 last:border-0">
              <td class="py-2 pr-3 whitespace-nowrap text-muted-foreground">{{ formatCallTime(call.created_at) }}</td>
              <td class="py-2 pr-3 whitespace-nowrap">{{ call.node_name || '-' }}</td>
              <td class="py-2 pr-3 whitespace-nowrap">{{ call.requested_model || call.model_name || '-' }}</td>
              <td class="py-2 pr-3 whitespace-nowrap">
                <Badge :variant="call.status === 'error' ? 'destructive' : call.status === 'running' ? 'outline' : 'secondary'" class="text-[10px]">
                  {{ call.status }}
                </Badge>
              </td>
              <td class="py-2 pr-3 text-left text-muted-foreground max-w-[200px] truncate" :title="call.error_message || ''">
                <span v-if="call.status === 'error' && call.error_message" class="text-destructive">{{ call.error_message }}</span>
                <span v-else-if="call.status === 'running'" class="text-muted-foreground">{{ t('admin.waiting') }}</span>
                <span v-else>-</span>
              </td>
              <td class="py-2 pr-3 text-right tabular-nums">{{ call.total_tokens || 0 }}</td>
              <td class="py-2 pr-3 text-right tabular-nums">{{ call.latency_ms || 0 }}ms</td>
              <td class="py-2 text-right tabular-nums">
                <div>{{ formatCost(call.cost) }}</div>
                <div class="text-[10px] text-muted-foreground">
                  {{ call.input_price_per_m != null || call.output_price_per_m != null ? `${formatCost(call.input_price_per_m || 0)}/${formatCost(call.output_price_per_m || 0)}` : '-' }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </details>
</template>
