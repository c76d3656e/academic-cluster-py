<script setup lang="ts">
import { ref } from 'vue'
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
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">审计日志</h2>
        <p class="text-sm text-muted-foreground mt-1">系统操作记录</p>
      </div>
    </div>

    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>用户</TableHead>
              <TableHead>操作</TableHead>
              <TableHead>资源类型</TableHead>
              <TableHead>IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-if="logs.length === 0">
              <TableCell colspan="5" class="text-center py-12 text-muted-foreground">
                暂无审计记录
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
