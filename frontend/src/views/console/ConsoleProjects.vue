<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { projectsApi, type Project } from '@/api/projects'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

const router = useRouter()
const projects = ref<Project[]>([])
const total = ref(0)
const isLoading = ref(true)

onMounted(async () => {
  try {
    const data = await projectsApi.listProjects()
    projects.value = data.projects
    total.value = data.total
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
})

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'completed': return 'default'
    case 'running': return 'secondary'
    case 'failed': return 'destructive'
    default: return 'outline'
  }
}
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">我的项目</h2>
        <p class="text-sm text-muted-foreground mt-1.5">共 {{ total }} 个项目</p>
      </div>
      <router-link to="/projects/new">
        <Button>新建项目</Button>
      </router-link>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">
      加载中...
    </div>

    <div v-else-if="projects.length === 0" class="text-center py-16">
      <p class="text-muted-foreground mb-5 text-body">暂无项目</p>
      <router-link to="/projects/new">
        <Button variant="outline">创建第一个项目</Button>
      </router-link>
    </div>

    <div v-else class="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="project in projects"
        :key="project.id"
        class="cursor-pointer hover:shadow-[var(--shadow-md)] transition-all duration-250 group"
        @click="router.push(`/projects/${project.id}`)"
      >
        <CardHeader class="pb-3">
          <div class="flex items-start justify-between gap-2">
            <CardTitle class="text-base truncate group-hover:text-foreground transition-colors">{{ project.name }}</CardTitle>
            <Badge :variant="getStatusVariant(project.status)" class="shrink-0">
              {{ project.status }}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p class="text-sm text-muted-foreground truncate mb-3">{{ project.query }}</p>
          <Separator class="mb-3" />
          <p class="text-caption text-muted-foreground">
            {{ project.created_at ? new Date(project.created_at).toLocaleDateString() : '' }}
          </p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
