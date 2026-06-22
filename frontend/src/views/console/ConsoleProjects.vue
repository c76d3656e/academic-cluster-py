<script setup lang="ts">
import { shallowRef, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { getStatusVariant } from '@/lib/utils'
import { projectsApi, type Project } from '@/api/projects'
import { consoleApi } from '@/api/console'
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

const projects = ref<Project[]>([])
const total = shallowRef(0)
const isLoading = shallowRef(true)
const actionLoading = shallowRef<string | null>(null)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  isLoading.value = true
  try {
    const data = await projectsApi.listProjects()
    projects.value = data.projects
    total.value = data.total
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

function isRunning(status: string): boolean {
  return status.startsWith('running')
}

function showResume(status: string): boolean {
  return status === 'interrupted' || status === 'failed'
}

async function handlePause(projectId: string) {
  actionLoading.value = projectId
  try {
    await consoleApi.controlPipeline(projectId, 'pause')
    await loadProjects()
  } catch {
    alert(t('project.pauseFailed'))
  } finally {
    actionLoading.value = null
  }
}

async function handleResume(projectId: string) {
  actionLoading.value = projectId
  try {
    await consoleApi.controlPipeline(projectId, 'resume')
    await loadProjects()
  } catch {
    alert(t('project.resumeFailed'))
  } finally {
    actionLoading.value = null
  }
}

async function handleDelete(projectId: string, name: string) {
  if (!confirm(t('project.confirmDelete', { name }))) return
  actionLoading.value = projectId
  try {
    await projectsApi.deleteProject(projectId)
    projects.value = projects.value.filter((p: Project) => p.id !== projectId)
    total.value--
  } catch {
    alert(t('project.deleteFailed'))
  } finally {
    actionLoading.value = null
  }
}
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('project.myProjects') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('project.totalProjects', { count: total }) }}</p>
      </div>
      <router-link to="/projects/new">
        <Button>{{ t('project.newProject') }}</Button>
      </router-link>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">{{ t('common.loading') }}</div>

    <div v-else-if="projects.length === 0" class="text-center py-16">
      <p class="text-muted-foreground mb-5 text-body">{{ t('project.noProjects') }}</p>
      <router-link to="/projects/new">
        <Button variant="outline">{{ t('project.createFirst') }}</Button>
      </router-link>
    </div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{{ t('project.projectName') }}</TableHead>
              <TableHead class="hidden md:table-cell">{{ t('project.queryLabel') }}</TableHead>
              <TableHead>{{ t('common.status') }}</TableHead>
              <TableHead class="hidden sm:table-cell">{{ t('project.createdAt') }}</TableHead>
              <TableHead>{{ t('common.actions') }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="p in projects" :key="p.id">
              <TableCell class="font-medium">{{ p.name }}</TableCell>
              <TableCell class="text-muted-foreground max-w-[200px] truncate hidden md:table-cell">{{ p.query }}</TableCell>
              <TableCell>
                <Badge :variant="getStatusVariant(p.status)" class="text-[0.65rem]">
                  {{ p.status }}
                </Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm hidden sm:table-cell">
                {{ p.created_at ? new Date(p.created_at).toLocaleDateString() : '-' }}
              </TableCell>
              <TableCell>
                <div class="flex gap-1 flex-wrap">
                  <Button variant="ghost" size="sm" @click="router.push(`/projects/${p.id}`)">
                    {{ t('common.view') }}
                  </Button>
                  <Button
                    v-if="isRunning(p.status)"
                    variant="ghost"
                    size="sm"
                    :disabled="actionLoading === p.id"
                    @click="handlePause(p.id)"
                  >
                    {{ actionLoading === p.id ? t('common.processing') : t('project.pause') }}
                  </Button>
                  <Button
                    v-if="showResume(p.status)"
                    variant="ghost"
                    size="sm"
                    :disabled="actionLoading === p.id"
                    @click="handleResume(p.id)"
                  >
                    {{ actionLoading === p.id ? t('common.processing') : t('project.resume') }}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-destructive hover:text-destructive"
                    :disabled="actionLoading === p.id"
                    @click="handleDelete(p.id, p.name)"
                  >
                    {{ actionLoading === p.id ? t('common.processing') : t('common.delete') }}
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
