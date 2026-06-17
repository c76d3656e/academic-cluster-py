<script setup lang="ts">
import { shallowRef, ref, onMounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from '@/i18n'
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
const { t } = useI18n()

const users = ref<User[]>([])
const totalUsers = shallowRef(0)
const isLoading = shallowRef(true)

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
    toast.success(u.is_active ? t('admin.userActivated') : t('admin.userDeactivated'))
  } catch {
    toast.error(t('admin.operationFailed'))
  }
}

async function changeRole(u: User, newRole: string) {
  try {
    await authApi.changeUserRole(u.id, newRole)
    u.role = newRole
    toast.success(t('admin.roleUpdated'))
  } catch {
    toast.error(t('admin.operationFailed'))
  }
}
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.userManagement') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.totalUsersCount', { count: totalUsers }) }}</p>
      </div>
      <!-- TODO: create user button -->
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">{{ t('common.loading') }}</div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{{ t('admin.email') }}</TableHead>
              <TableHead class="hidden sm:table-cell">{{ t('admin.name') }}</TableHead>
              <TableHead>{{ t('admin.role') }}</TableHead>
              <TableHead>{{ t('admin.status') }}</TableHead>
              <TableHead class="hidden md:table-cell">{{ t('admin.registeredAt') }}</TableHead>
              <TableHead>{{ t('common.actions') }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="u in users" :key="u.id">
              <TableCell class="font-medium max-w-[160px] truncate">{{ u.email }}</TableCell>
              <TableCell class="hidden sm:table-cell">{{ u.full_name || '-' }}</TableCell>
              <TableCell>
                <Select
                  :model-value="u.role"
                  @update:model-value="(val: any) => { if (typeof val === 'string') changeRole(u, val) }"
                  :disabled="u.id === user?.id"
                >
                  <SelectTrigger class="w-20 md:w-24 h-8">
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
                  {{ u.is_active ? t('common.active') : t('common.inactive') }}
                </Badge>
              </TableCell>
              <TableCell class="text-muted-foreground hidden md:table-cell">
                {{ u.created_at ? new Date(u.created_at).toLocaleDateString() : '-' }}
              </TableCell>
              <TableCell>
                <Button
                  v-if="u.id !== user?.id"
                  @click="toggleActive(u)"
                  :variant="u.is_active ? 'destructive' : 'default'"
                  size="sm"
                >
                  {{ u.is_active ? t('admin.deactivate') : t('admin.activate') }}
                </Button>
                <span v-else class="text-muted-foreground text-sm">{{ t('auth.currentUser') }}</span>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
