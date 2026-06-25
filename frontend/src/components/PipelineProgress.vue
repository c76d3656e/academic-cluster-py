<script setup lang="ts">
import { useI18n } from '@/i18n'
import type { ProgressLog } from '@/composables/useProjectProgress'
import { PIPELINE_STAGES } from '@/composables/useProjectProgress'

const { t } = useI18n()

defineProps<{
  isRunning: boolean
  completedNodes: Set<string>
  progressLogs: ProgressLog[]
  currentProgressNode: string
  progressMessage: string
  projectStatus: string
}>()

const pipelineStages = PIPELINE_STAGES
</script>

<template>
  <div class="my-6">
    <!-- Progress Bar -->
    <div class="border border-border rounded-xl bg-card p-5 mb-4">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span v-if="isRunning" class="relative flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
          <span class="text-sm font-medium">
            {{ isRunning ? t('pipeline.executing') : projectStatus === 'completed' ? t('pipeline.done') : t('pipeline.stopped') }}
          </span>
        </div>
        <span class="text-xs text-muted-foreground tabular-nums">
          {{ t('pipeline.stages', { completed: completedNodes.size, total: pipelineStages.length }) }}
        </span>
      </div>

      <!-- Progress Bar -->
      <div class="progress-bar-track">
        <div
          class="progress-bar-fill"
          :class="{ 'progress-bar-failed': projectStatus === 'failed' }"
          :style="{ width: Math.round((completedNodes.size / pipelineStages.length) * 100) + '%' }"
        />
      </div>

      <!-- Current Stage -->
      <div class="flex items-center justify-between mt-3">
        <div class="flex items-center gap-2 text-sm">
          <template v-if="currentProgressNode">
            <span>{{ pipelineStages.find(s => s.key === currentProgressNode)?.icon }}</span>
            <span class="font-medium">{{ pipelineStages.find(s => s.key === currentProgressNode)?.label }}</span>
          </template>
          <template v-else-if="projectStatus === 'completed'">
            <span>✅</span>
            <span class="font-medium">{{ t('pipeline.allDone') }}</span>
          </template>
        </div>
        <span class="text-xs text-muted-foreground">
          {{ progressMessage || '' }}
        </span>
      </div>
    </div>

    <!-- Log Panel (collapsible) -->
    <details class="border border-border rounded-xl bg-card overflow-hidden">
      <summary class="px-5 py-3 text-sm font-medium cursor-pointer hover:bg-muted/50 transition-colors">
        {{ t('pipeline.executionLog', { count: progressLogs.length }) }}
      </summary>
      <div class="max-h-64 overflow-y-auto space-y-1 font-mono text-xs text-muted-foreground px-5 pb-4">
        <div v-for="(log, i) in [...progressLogs].reverse()" :key="i" class="flex gap-2 py-1 border-b border-border/50 last:border-0">
          <span class="shrink-0 tabular-nums text-muted-foreground/60">{{ log.time }}</span>
          <span v-if="log.node" class="shrink-0 text-foreground/40">[{{ log.node }}]</span>
          <span class="text-foreground/70">{{ log.message }}</span>
        </div>
        <div v-if="progressLogs.length === 0" class="text-center py-4 text-muted-foreground/50">
          {{ t('pipeline.waitingLog') }}
        </div>
      </div>
    </details>
  </div>
</template>

<style scoped>
.progress-bar-track {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: var(--muted);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: oklch(0.65 0.15 145);
  transition: width 0.6s ease;
}

.progress-bar-failed {
  background: oklch(0.65 0.15 25);
}
</style>
