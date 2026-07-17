<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from '@/i18n'
import { adminApi, type AuditLog } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'

const { t } = useI18n()

const PAGE_SIZE = 50

const logs = ref<AuditLog[]>([])
const total = shallowRef(0)
const page = shallowRef(0)
const isLoading = shallowRef(true)
const loadFailed = shallowRef(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

async function loadLogs() {
  isLoading.value = true
  loadFailed.value = false
  try {
    const data = await adminApi.getAuditLogs({
      skip: page.value * PAGE_SIZE,
      limit: PAGE_SIZE,
    })
    logs.value = data.logs
    total.value = data.total
  } catch {
    logs.value = []
    loadFailed.value = true
  } finally {
    isLoading.value = false
  }
}

async function changePage(nextPage: number) {
  page.value = Math.max(0, Math.min(nextPage, pageCount.value - 1))
  await loadLogs()
}

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '-'
}

onMounted(loadLogs)
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.auditLog') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">
          {{ t('admin.auditLogDesc') }} · {{ t('admin.auditRecordsCount', { count: total }) }}
        </p>
      </div>
    </div>

    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{{ t('common.time') }}</TableHead>
              <TableHead>{{ t('project.user') }}</TableHead>
              <TableHead>{{ t('admin.action') }}</TableHead>
              <TableHead>{{ t('admin.resourceType') }}</TableHead>
              <TableHead>{{ t('admin.ip') }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-if="isLoading">
              <TableCell colspan="5" class="text-center py-12 text-muted-foreground">
                {{ t('common.loading') }}
              </TableCell>
            </TableRow>
            <TableRow v-else-if="loadFailed">
              <TableCell colspan="5" class="text-center py-12 text-muted-foreground">
                <div class="space-y-3">
                  <p>{{ t('admin.auditLoadFailed') }}</p>
                  <Button variant="outline" size="sm" @click="loadLogs">{{ t('emptyState.retry') }}</Button>
                </div>
              </TableCell>
            </TableRow>
            <TableRow v-else-if="logs.length === 0">
              <TableCell colspan="5" class="text-center py-12 text-muted-foreground">
                {{ t('admin.noAuditRecords') }}
              </TableCell>
            </TableRow>
            <TableRow v-for="log in logs" :key="log.id">
              <TableCell class="text-muted-foreground text-caption">
                {{ formatTimestamp(log.created_at) }}
              </TableCell>
              <TableCell class="font-mono text-caption">{{ log.user_id }}</TableCell>
              <TableCell>
                <Badge variant="outline" class="text-[0.65rem]">{{ log.action }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ log.resource_type || '-' }}</TableCell>
              <TableCell class="text-muted-foreground text-caption font-mono">{{ log.ip_address || '-' }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!isLoading && !loadFailed && total > 0" class="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
          <span class="text-xs text-muted-foreground">
            {{ t('dataTable.page', { current: page + 1, total: pageCount }) }}
          </span>
          <div class="flex gap-2">
            <Button variant="outline" size="sm" :disabled="page === 0" @click="changePage(page - 1)">
              {{ t('pagination.previous') }}
            </Button>
            <Button variant="outline" size="sm" :disabled="page + 1 >= pageCount" @click="changePage(page + 1)">
              {{ t('pagination.next') }}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
