<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { Separator } from '@/components/ui/separator'

const route = useRoute()
const router = useRouter()
const { user, isAdmin, logout } = useAuth()

interface NavItem {
  path: string
  label: string
  icon: string
}

const consoleItems: NavItem[] = [
  { path: '/console/overview', label: '仪表盘', icon: 'dashboard' },
  { path: '/console/projects', label: '我的项目', icon: 'projects' },
  { path: '/console/usage', label: '我的用量', icon: 'usage' },
  { path: '/console/profile', label: '个人设置', icon: 'profile' },
  { path: '/console/recharge', label: '充值', icon: 'recharge' },
]

const adminItems: NavItem[] = [
  { path: '/admin/overview', label: '系统概览', icon: 'admin-overview' },
  { path: '/admin/users', label: '用户管理', icon: 'admin-users' },
  { path: '/admin/projects', label: '项目管理', icon: 'admin-projects' },
  { path: '/admin/providers', label: 'Provider 管理', icon: 'admin-providers' },
  { path: '/admin/pipeline-config', label: 'Pipeline 配置', icon: 'admin-pipeline' },
  { path: '/admin/usage', label: '用量分析', icon: 'admin-usage' },
  { path: '/admin/audit', label: '审计日志', icon: 'admin-audit' },
]

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

async function handleLogout() {
  await logout()
  router.push('/login')
}

function getInitials(email: string): string {
  return email.slice(0, 2).toUpperCase()
}
</script>

<template>
  <aside class="w-[220px] shrink-0 border-r border-border bg-sidebar h-screen sticky top-0 flex flex-col">
    <!-- Logo -->
    <div class="px-5 py-5">
      <router-link to="/console/overview" class="text-sm font-semibold text-foreground tracking-tight">
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

    <Separator />

    <!-- Console Navigation -->
    <nav class="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
      <p class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground px-2 mb-2">
        我的控制台
      </p>
      <router-link
        v-for="item in consoleItems"
        :key="item.path"
        :to="item.path"
        class="sidebar-link"
        :class="{ 'sidebar-link-active': isActive(item.path) }"
      >
        <span class="sidebar-icon">{{ getIcon(item.icon) }}</span>
        {{ item.label }}
      </router-link>

      <!-- Admin Section -->
      <template v-if="isAdmin">
        <Separator class="my-3" />
        <p class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground px-2 mb-2">
          系统管理
        </p>
        <router-link
          v-for="item in adminItems"
          :key="item.path"
          :to="item.path"
          class="sidebar-link"
          :class="{ 'sidebar-link-active': isActive(item.path) }"
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
        @click="handleLogout"
        class="sidebar-link text-destructive hover:text-destructive w-full"
      >
        <span class="sidebar-icon">&#x2192;</span>
        登出
      </button>
    </div>
  </aside>
</template>

<script lang="ts">
function getIcon(icon: string): string {
  const icons: Record<string, string> = {
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
  return icons[icon] || '□'
}
</script>

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
