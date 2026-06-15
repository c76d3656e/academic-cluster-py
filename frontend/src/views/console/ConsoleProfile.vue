<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { consoleApi } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'vue-sonner'

const { user } = useAuth()

const fullName = ref(user.value?.full_name || '')
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const isSaving = ref(false)
const isChangingPassword = ref(false)

async function saveProfile() {
  isSaving.value = true
  try {
    await consoleApi.updateProfile({ full_name: fullName.value })
    toast.success('个人信息已更新')
  } catch {
    toast.error('保存失败')
  } finally {
    isSaving.value = false
  }
}

async function changePassword() {
  if (newPassword.value !== confirmPassword.value) {
    toast.error('两次密码不一致')
    return
  }
  if (newPassword.value.length < 6) {
    toast.error('密码至少 6 位')
    return
  }
  isChangingPassword.value = true
  try {
    await consoleApi.changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    toast.success('密码已修改')
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch {
    toast.error('修改失败')
  } finally {
    isChangingPassword.value = false
  }
}
</script>

<template>
  <div class="p-8 max-w-2xl">
    <h2 class="text-heading font-medium tracking-tight mb-8">个人设置</h2>

    <!-- Account Info -->
    <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
      <CardHeader>
        <CardTitle class="text-base">账户信息</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <div>
          <Label class="text-caption text-muted-foreground">邮箱</Label>
          <p class="text-sm mt-1">{{ user?.email }}</p>
        </div>
        <div>
          <Label class="text-caption text-muted-foreground">角色</Label>
          <p class="text-sm mt-1">{{ user?.role }}</p>
        </div>
        <div>
          <Label for="fullName" class="text-caption text-muted-foreground">昵称</Label>
          <Input id="fullName" v-model="fullName" class="mt-1" placeholder="输入昵称" />
        </div>
        <Button @click="saveProfile" :disabled="isSaving" size="sm">
          {{ isSaving ? '保存中...' : '保存' }}
        </Button>
      </CardContent>
    </Card>

    <!-- Change Password -->
    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-base">修改密码</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <div>
          <Label for="currentPwd" class="text-caption text-muted-foreground">当前密码</Label>
          <Input id="currentPwd" v-model="currentPassword" type="password" class="mt-1" />
        </div>
        <div>
          <Label for="newPwd" class="text-caption text-muted-foreground">新密码</Label>
          <Input id="newPwd" v-model="newPassword" type="password" class="mt-1" />
        </div>
        <div>
          <Label for="confirmPwd" class="text-caption text-muted-foreground">确认密码</Label>
          <Input id="confirmPwd" v-model="confirmPassword" type="password" class="mt-1" />
        </div>
        <Button @click="changePassword" :disabled="isChangingPassword" size="sm">
          {{ isChangingPassword ? '修改中...' : '修改密码' }}
        </Button>
      </CardContent>
    </Card>
  </div>
</template>
