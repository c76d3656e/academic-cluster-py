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
  <aside class="w-48 lg:w-56 xl:w-64 shrink-0 border-r border-border bg-sidebar h-full flex flex-col">
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

    <!-- GitHub Link -->
    <div class="px-3 pt-3">
      <a
        href="https://github.com/c76d3656e/academic-cluster-py"
        target="_blank"
        rel="noopener noreferrer"
        class="sidebar-link"
      >
        <svg viewBox="0 0 24 24" class="sidebar-icon size-4" fill="currentColor" style="opacity: 0.5;">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
        </svg>
        GitHub
      </a>
    </div>

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
