<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { authApi, type User } from '@/api/auth'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'vue-sonner'

const { user } = useAuth()

const users = ref<User[]>([])
const totalUsers = ref(0)
const isLoading = ref(true)

onMounted(async () => {
  try {
    const data = await authApi.listUsers(0, 50)
    users.value = data.users
    totalUsers.value = data.total
  } catch {
    // ignore
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
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">用户管理</h2>
        <p class="text-sm text-muted-foreground mt-1">共 {{ totalUsers }} 个用户</p>
      </div>
      <!-- TODO: create user button -->
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">加载中...</div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
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
  </div>
</template>
