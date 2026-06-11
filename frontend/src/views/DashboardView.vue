<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { projectsApi, type Project } from '../api/projects'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Separator } from '@/components/ui/separator'


const router = useRouter()
const { user, isAdmin, logout } = useAuth()

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

async function handleLogout() {
  await logout()
  router.push('/login')
}

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'completed': return 'default'
    case 'running': return 'secondary'
    case 'failed': return 'destructive'
    default: return 'outline'
  }
}

function getInitials(email: string): string {
  return email.slice(0, 2).toUpperCase()
}
</script>

<template>
  <div class="min-h-screen bg-muted/30">
    <!-- Header -->
    <header class="bg-background border-b sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <h1 class="text-lg font-semibold">Academic Cluster</h1>
        <div class="flex items-center gap-3">
          <router-link v-if="isAdmin" to="/admin">
            <Button variant="ghost" size="sm">管理后台</Button>
          </router-link>
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button variant="ghost" size="icon" class="rounded-full">
                <Avatar class="size-8">
                  <AvatarFallback>{{ user?.email ? getInitials(user.email) : 'U' }}</AvatarFallback>
                </Avatar>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-48">
              <DropdownMenuItem class="text-xs text-muted-foreground" disabled>
                {{ user?.email }}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem @click="handleLogout" class="text-destructive">
                登出
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>

    <!-- Main -->
    <main class="max-w-7xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <div>
          <h2 class="text-xl font-semibold">我的项目</h2>
          <p class="text-sm text-muted-foreground mt-1">共 {{ total }} 个项目</p>
        </div>
        <router-link to="/projects/new">
          <Button>新建项目</Button>
        </router-link>
      </div>

      <div v-if="isLoading" class="text-center py-12 text-muted-foreground">
        加载中...
      </div>

      <div v-else-if="projects.length === 0" class="text-center py-12">
        <p class="text-muted-foreground mb-4">暂无项目</p>
        <router-link to="/projects/new">
          <Button variant="outline">创建第一个项目</Button>
        </router-link>
      </div>

      <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card
          v-for="project in projects"
          :key="project.id"
          class="cursor-pointer hover:shadow-md transition-shadow"
          @click="router.push(`/projects/${project.id}`)"
        >
          <CardHeader class="pb-3">
            <div class="flex items-start justify-between gap-2">
              <CardTitle class="text-base truncate">{{ project.name }}</CardTitle>
              <Badge :variant="getStatusVariant(project.status)" class="shrink-0">
                {{ project.status }}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p class="text-sm text-muted-foreground truncate mb-3">{{ project.query }}</p>
            <Separator class="mb-2" />
            <p class="text-xs text-muted-foreground">
              {{ project.created_at ? new Date(project.created_at).toLocaleDateString() : '' }}
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  </div>
</template>
