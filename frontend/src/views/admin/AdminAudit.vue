<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
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

const logs = ref<Array<{
  id: string
  time: string
  user_email: string
  action: string
  resource_type: string
  ip_address: string
  details: Record<string, unknown>
}>>([])
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.auditLog') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.auditLogDesc') }}</p>
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
            <TableRow v-if="logs.length === 0">
              <TableCell colspan="5" class="text-center py-12 text-muted-foreground">
                {{ t('admin.noAuditRecords') }}
              </TableCell>
            </TableRow>
            <TableRow v-for="log in logs" :key="log.id">
              <TableCell class="text-muted-foreground text-caption">
                {{ new Date(log.time).toLocaleString() }}
              </TableCell>
              <TableCell class="font-medium text-sm">{{ log.user_email }}</TableCell>
              <TableCell>
                <Badge variant="outline" class="text-[0.65rem]">{{ log.action }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ log.resource_type }}</TableCell>
              <TableCell class="text-muted-foreground text-caption font-mono">{{ log.ip_address }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
