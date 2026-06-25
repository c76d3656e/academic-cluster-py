<script setup lang="ts">
import { shallowRef, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { getStatusVariant } from '@/lib/utils'
import { adminApi, type ProjectAdmin } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const router = useRouter()
const { t } = useI18n()

const projects = ref<ProjectAdmin[]>([])
const total = shallowRef(0)
const isLoading = shallowRef(true)
const deletingId = shallowRef<string | null>(null)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  isLoading.value = true
  try {
    const data = await adminApi.listAllProjects({ skip: 0, limit: 200 })
    projects.value = data.projects
    total.value = data.total
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

async function handleDelete(id: string, name: string) {
  if (!confirm(t('project.confirmDeleteSimple', { name }))) return
  deletingId.value = id
  try {
    await adminApi.deleteProject(id)
    projects.value = projects.value.filter(p => p.id !== id)
    total.value--
  } catch {
    alert(t('project.deleteFailed'))
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.projectManagement') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.totalProjectsCount', { count: total }) }}</p>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">{{ t('common.loading') }}</div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{{ t('project.projectName') }}</TableHead>
              <TableHead class="hidden md:table-cell">{{ t('admin.queryLabel') }}</TableHead>
              <TableHead class="hidden md:table-cell">{{ t('admin.userLabel') }}</TableHead>
              <TableHead>{{ t('common.status') }}</TableHead>
              <TableHead class="hidden sm:table-cell">{{ t('admin.createdAt') }}</TableHead>
              <TableHead>{{ t('common.actions') }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="p in projects" :key="p.id">
              <TableCell class="font-medium">{{ p.name }}</TableCell>
              <TableCell class="text-muted-foreground max-w-[200px] truncate hidden md:table-cell">{{ p.query }}</TableCell>
              <TableCell class="text-muted-foreground text-sm hidden md:table-cell">{{ p.user_name || p.user_email || '-' }}</TableCell>
              <TableCell>
                <Badge :variant="getStatusVariant(p.status)" class="text-[0.65rem]">
                  {{ p.status }}
                </Badge>
              </TableCell>
              <TableCell class="text-muted-foreground hidden sm:table-cell">
                {{ p.created_at ? new Date(p.created_at).toLocaleDateString() : '-' }}
              </TableCell>
              <TableCell>
                <div class="flex gap-1 flex-wrap">
                  <Button variant="ghost" size="sm" @click="router.push(`/projects/${p.id}`)">
                    {{ t('common.view') }}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-destructive hover:text-destructive"
                    :disabled="deletingId === p.id"
                    @click="handleDelete(p.id, p.name)"
                  >
                    {{ deletingId === p.id ? t('common.deleting') : t('common.delete') }}
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
