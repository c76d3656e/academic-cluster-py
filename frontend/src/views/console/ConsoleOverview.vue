<script setup lang="ts">
import { shallowRef, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from '@/i18n'
import { getStatusVariant } from '@/lib/utils'
import { consoleApi, type ConsoleOverview as ConsoleOverviewData } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const router = useRouter()
const { user } = useAuth()
const { t } = useI18n()

const overview = shallowRef<ConsoleOverviewData | null>(null)
const isLoading = shallowRef(true)

onMounted(async () => {
  try {
    overview.value = await consoleApi.getOverview()
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="p-4 md:p-8">
    <!-- Welcome -->
    <div class="mb-8">
      <h2 class="text-heading font-medium tracking-tight">{{ t('console.welcomeBack') }}</h2>
      <p class="text-sm text-muted-foreground mt-1">{{ user?.full_name || user?.email }}</p>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-5 mb-8">
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.totalProjects') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.project_count ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.running') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.running_projects ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.totalPapers') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_papers ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.tokenUsage') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ (overview?.total_tokens ?? 0).toLocaleString() }}</p>
          <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ t('console.costAmount', { cost: (overview?.total_cost ?? 0).toFixed(4) }) }}</p>
        </CardContent>
      </Card>
    </div>

    <!-- Recent Projects -->
    <div class="mb-8">
      <div class="flex items-center justify-between gap-3 mb-4">
        <h3 class="text-base font-medium">{{ t('console.recentProjects') }}</h3>
        <router-link to="/console/projects" class="shrink-0">
          <Button variant="ghost" size="sm">{{ t('common.viewAll') }}</Button>
        </router-link>
      </div>

      <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">{{ t('common.loading') }}</div>

      <div v-else-if="!overview || overview.recent_projects.length === 0" class="text-center py-8">
        <p class="text-muted-foreground text-sm mb-4">{{ t('project.noProjects') }}</p>
        <router-link to="/projects/new">
          <Button size="sm">{{ t('project.createFirst') }}</Button>
        </router-link>
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="project in overview.recent_projects"
          :key="project.id"
          class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors"
          @click="router.push(`/projects/${project.id}`)"
        >
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium truncate">{{ project.name }}</p>
          </div>
          <div class="flex items-center gap-3 shrink-0">
            <Badge :variant="getStatusVariant(project.status)" class="text-[0.65rem] shrink-0">
              {{ project.status }}
            </Badge>
            <span class="text-caption text-muted-foreground shrink-0">
              {{ project.created_at ? new Date(project.created_at).toLocaleDateString() : '' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div>
      <h3 class="text-base font-medium mb-4">{{ t('console.quickActions') }}</h3>
      <div class="flex gap-3 flex-wrap">
        <router-link to="/projects/new">
          <Button>{{ t('project.newProject') }}</Button>
        </router-link>
        <router-link to="/console/usage">
          <Button variant="outline">{{ t('console.viewUsage') }}</Button>
        </router-link>
        <router-link to="/console/recharge">
          <Button variant="outline" disabled>{{ t('console.rechargeNotOpen') }}</Button>
        </router-link>
      </div>
    </div>
  </div>
</template>
