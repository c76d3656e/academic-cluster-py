<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useFeatures } from '@/composables/useFeatures'
import { useI18n } from '@/i18n'
import { getInitials } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'
import { GlobalSearch } from '@/components/global-search'
import { CommandMenu } from '@/components/command-menu'
import type { SearchSource } from '@/components/global-search'

const emit = defineEmits<{ navigate: [] }>()

const route = useRoute()
const router = useRouter()
const { user, logout } = useAuth()
const isAdmin = computed(() => useAuth().isAdmin)
const { features, loadFeatures } = useFeatures()
const { t } = useI18n()

// Command menu state
const commandMenuOpen = ref(false)

// Search sources for GlobalSearch
const searchSources = computed<SearchSource[]>(() => [
  {
    label: t('console.myProjects'),
    items: [],
    toResult: (item: unknown) => ({
      id: '1',
      title: 'Example Project',
      href: '/console/projects/1',
      icon: 'projects',
    }),
    search: (query) => {
      // This would typically call an API
      return [
        { id: '1', title: 'Example Project', href: '/console/projects/1', icon: 'projects' },
      ]
    },
  },
])

// Command menu groups
const commandGroups = computed(() => {
  const groups = []

  // Console commands
  groups.push({
    id: 'console',
    label: t('console.myConsole'),
    items: [
      {
        id: 'dashboard',
        label: t('console.dashboard'),
        icon: 'dashboard',
        action: () => { router.push('/console/overview') },
      },
      {
        id: 'projects',
        label: t('console.myProjects'),
        icon: 'projects',
        action: () => { router.push('/console/projects') },
      },
      {
        id: 'new-project',
        label: t('project.newProject'),
        icon: 'create',
        action: () => { router.push('/console/projects/new') },
      },
      {
        id: 'profile',
        label: t('console.profile'),
        icon: 'profile',
        action: () => { router.push('/console/profile') },
      },
      {
        id: 'recharge',
        label: t('console.recharge'),
        icon: 'recharge',
        action: () => { router.push('/console/recharge') },
      },
    ],
  })

  // Admin commands
  if (isAdmin.value) {
    groups.push({
      id: 'admin',
      label: t('admin.systemManagement'),
      items: [
        {
          id: 'admin-overview',
          label: t('admin.systemOverview'),
          icon: 'admin-overview',
          action: () => { router.push('/admin/overview') },
        },
        {
          id: 'admin-users',
          label: t('admin.userManagement'),
          icon: 'admin-users',
          action: () => { router.push('/admin/users') },
        },
        {
          id: 'admin-projects',
          label: t('admin.projectManagement'),
          icon: 'admin-projects',
          action: () => { router.push('/admin/projects') },
        },
        {
          id: 'admin-providers',
          label: t('admin.providerManagement'),
          icon: 'admin-providers',
          action: () => { router.push('/admin/providers') },
        },
      ],
    })
  }

  return groups
})

const showUsage = computed(() => features.value.show_usage ?? false)

interface NavItem {
  path: string
  label: string
  icon: string
}

const consoleItems = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { path: '/console/overview', label: t('console.dashboard'), icon: 'dashboard' },
    { path: '/console/projects', label: t('console.myProjects'), icon: 'projects' },
  ]
  if (showUsage.value) {
    items.push({ path: '/console/usage', label: t('console.myUsage'), icon: 'usage' })
  }
  items.push({ path: '/console/profile', label: t('console.profile'), icon: 'profile' })
  items.push({ path: '/console/recharge', label: t('console.recharge'), icon: 'recharge' })
  return items
})

const adminItems: NavItem[] = [
  { path: '/admin/overview', label: t('admin.systemOverview'), icon: 'admin-overview' },
  { path: '/admin/users', label: t('admin.userManagement'), icon: 'admin-users' },
  { path: '/admin/projects', label: t('admin.projectManagement'), icon: 'admin-projects' },
  { path: '/admin/providers', label: t('admin.providerManagement'), icon: 'admin-providers' },
  { path: '/admin/pipeline-config', label: t('admin.pipelineConfig'), icon: 'admin-pipeline' },
  { path: '/admin/usage', label: t('admin.usageAnalysis'), icon: 'admin-usage' },
  { path: '/admin/audit', label: t('admin.auditLog'), icon: 'admin-audit' },
]

const iconMap: Record<string, string> = {
  'dashboard': '■',
  'projects': '▣',
  'usage': '▲',
  'profile': '○',
  'recharge': '◆',
  'admin-overview': '▓',
  'admin-users': '▤',
  'admin-projects': '▦',
  'admin-providers': '◈',
  'admin-pipeline': '⚙',
  'admin-usage': '▴',
  'admin-audit': '▨',
}

function getIcon(icon: string): string {
  return iconMap[icon] || '□'
}

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

function handleNavigate() {
  emit('navigate')
}

async function handleLogout() {
  await logout()
  router.push('/login')
}

onMounted(async () => {
  await loadFeatures()
})
</script>

<template>
  <aside class="w-[220px] shrink-0 border-r border-border bg-sidebar h-full flex flex-col overflow-x-hidden">
    <!-- Logo -->
    <div class="px-5 py-5">
      <router-link to="/console/overview" class="text-sm font-semibold text-foreground tracking-tight" @click="handleNavigate">
        Academic Cluster
      </router-link>
    </div>

    <!-- User Info -->
    <div class="px-5 pb-4">
      <div class="flex items-center gap-2.5">
        <div class="size-7 rounded-full bg-muted flex items-center justify-center text-[0.65rem] font-medium text-muted-foreground">
          {{ user?.email ? getInitials(user.email) : 'U' }}
        </div>
        <div class="min-w-0 flex-1">
          <p class="text-xs font-medium text-foreground truncate">{{ user?.full_name || user?.email }}</p>
          <p class="text-[0.65rem] text-muted-foreground truncate">{{ user?.email }}</p>
        </div>
      </div>
    </div>

    <!-- Global Search -->
    <div class="px-3 pb-3">
      <GlobalSearch
        :sources="searchSources"
        :placeholder="t('common.search')"
        @select="(item: any) => console.log('Selected:', item)"
      />
    </div>

    <Separator />

    <!-- Console Navigation -->
    <nav class="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
      <p class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground px-2 mb-2">
        {{ t('console.myConsole') }}
      </p>
      <router-link
        v-for="item in consoleItems"
        :key="item.path"
        :to="item.path"
        class="sidebar-link"
        :class="{ 'sidebar-link-active': isActive(item.path) }"
        @click="handleNavigate"
      >
        <span class="sidebar-icon">{{ getIcon(item.icon) }}</span>
        {{ item.label }}
      </router-link>

      <!-- Admin Section -->
      <template v-if="isAdmin">
        <Separator class="my-3" />
        <p class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground px-2 mb-2">
          {{ t('admin.systemManagement') }}
        </p>
        <router-link
          v-for="item in adminItems"
          :key="item.path"
          :to="item.path"
          class="sidebar-link"
          :class="{ 'sidebar-link-active': isActive(item.path) }"
          @click="handleNavigate"
        >
          <span class="sidebar-icon">{{ getIcon(item.icon) }}</span>
          {{ item.label }}
        </router-link>
      </template>
    </nav>

    <Separator />

    <!-- Logout -->
    <div class="px-3 py-3">
      <button
        class="sidebar-link text-destructive hover:text-destructive w-full"
        @click="handleLogout"
      >
        <span class="sidebar-icon">&#x2192;</span>
        {{ t('auth.logout') }}
      </button>
    </div>

    <!-- Command Menu (Cmd+K) -->
    <CommandMenu
      v-model:open="commandMenuOpen"
      :groups="commandGroups"
    />
  </aside>
</template>

<style scoped>
.sidebar-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.4;
  color: var(--muted-foreground);
  text-decoration: none;
  border-radius: var(--radius-md);
  transition: color 0.15s, background-color 0.15s;
}

.sidebar-link:hover {
  color: var(--foreground);
  background: var(--sidebar-accent);
}

.sidebar-link-active {
  color: var(--foreground);
  font-weight: 500;
  background: var(--sidebar-accent);
}

.sidebar-icon {
  font-size: 0.75rem;
  width: 1rem;
  text-align: center;
  opacity: 0.5;
  flex-shrink: 0;
}

.sidebar-link-active .sidebar-icon {
  opacity: 0.9;
}
</style>
