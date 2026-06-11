<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { authApi, type User, type SystemStats } from '../api/auth'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'vue-sonner'

const router = useRouter()
const { user } = useAuth()

const stats = ref<SystemStats | null>(null)
const users = ref<User[]>([])
const totalUsers = ref(0)
const isLoading = ref(true)

onMounted(async () => {
  try {
    const [statsData, usersData] = await Promise.all([
      authApi.getSystemStats(),
      authApi.listUsers(0, 50),
    ])
    stats.value = statsData
    users.value = usersData.users
    totalUsers.value = usersData.total
  } catch {
    router.push('/')
  } finally {
    isLoading.value = false
  }
})

async function toggleActive(u: User) {
  try {
    await authApi.toggleUserActive(u.id, !u.is_active)
    u.is_active = !u.is_active
    toast.success(u.is_active ? '用户已激活' : '用户已停用')
  } catch {
    toast.error('操作失败')
  }
}

async function changeRole(u: User, newRole: string) {
  try {
    await authApi.changeUserRole(u.id, newRole)
    u.role = newRole
    toast.success('角色已更新')
  } catch {
    toast.error('操作失败')
  }
}
</script>

<template>
  <div class="min-h-screen bg-background">
    <header class="bg-background border-b border-border">
      <div class="container-standard px-6 py-4 flex items-center gap-3">
        <router-link to="/">
          <Button variant="ghost" size="sm">&larr; 返回</Button>
        </router-link>
        <h1 class="text-lg font-semibold tracking-tight">管理后台</h1>
      </div>
    </header>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">加载中...</div>

    <main v-else class="container-standard px-6 py-10">
      <!-- 系统统计 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-5 mb-10">
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总用户数</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ stats?.total_users || 0 }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">活跃用户</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ stats?.active_users || 0 }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总项目数</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ stats?.total_projects || 0 }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总论文数</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ stats?.total_papers || 0 }}</p>
          </CardContent>
        </Card>
      </div>

      <!-- 用户管理 -->
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle class="text-heading">用户管理</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>邮箱</TableHead>
                <TableHead>姓名</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>注册时间</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="u in users" :key="u.id">
                <TableCell class="font-medium">{{ u.email }}</TableCell>
                <TableCell>{{ u.full_name || '-' }}</TableCell>
                <TableCell>
                  <Select
                    :model-value="u.role"
                    @update:model-value="(val: any) => { if (typeof val === 'string') changeRole(u, val) }"
                    :disabled="u.id === user?.id"
                  >
                    <SelectTrigger class="w-24 h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="user">user</SelectItem>
                      <SelectItem value="admin">admin</SelectItem>
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Badge :variant="u.is_active ? 'default' : 'destructive'">
                    {{ u.is_active ? '活跃' : '停用' }}
                  </Badge>
                </TableCell>
                <TableCell class="text-muted-foreground">
                  {{ u.created_at ? new Date(u.created_at).toLocaleDateString() : '-' }}
                </TableCell>
                <TableCell>
                  <Button
                    v-if="u.id !== user?.id"
                    @click="toggleActive(u)"
                    :variant="u.is_active ? 'destructive' : 'default'"
                    size="sm"
                  >
                    {{ u.is_active ? '停用' : '激活' }}
                  </Button>
                  <span v-else class="text-muted-foreground text-sm">当前用户</span>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </main>
  </div>
</template>
