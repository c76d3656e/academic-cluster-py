<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { toast } from 'vue-sonner'

const router = useRouter()
const { register, isLoading } = useAuth()

const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const fullName = ref('')

async function handleRegister() {
  if (password.value !== confirmPassword.value) {
    toast.error('两次输入的密码不一致')
    return
  }

  try {
    await register(email.value, password.value, fullName.value || undefined)
    toast.success('注册成功')
    router.push('/')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || '注册失败，请重试')
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-muted/30 p-4">
    <Card class="w-full max-w-md">
      <CardHeader class="text-center">
        <CardTitle class="text-2xl">Academic Cluster</CardTitle>
        <CardDescription>创建新账户</CardDescription>
      </CardHeader>
      <CardContent>
        <form @submit.prevent="handleRegister" class="space-y-4">
          <div class="space-y-2">
            <Label for="fullName">姓名</Label>
            <Input id="fullName" v-model="fullName" type="text" placeholder="可选" />
          </div>

          <div class="space-y-2">
            <Label for="email">邮箱</Label>
            <Input id="email" v-model="email" type="email" required placeholder="your@email.com" />
          </div>

          <div class="space-y-2">
            <Label for="password">密码</Label>
            <Input id="password" v-model="password" type="password" required minlength="8" placeholder="至少 8 位" />
          </div>

          <div class="space-y-2">
            <Label for="confirmPassword">确认密码</Label>
            <Input id="confirmPassword" v-model="confirmPassword" type="password" required minlength="8" placeholder="再次输入密码" />
          </div>

          <Button type="submit" class="w-full" :disabled="isLoading">
            {{ isLoading ? '注册中...' : '注册' }}
          </Button>
        </form>

        <p class="mt-4 text-center text-sm text-muted-foreground">
          已有账户？
          <router-link to="/login" class="text-primary hover:underline">登录</router-link>
        </p>
      </CardContent>
    </Card>
  </div>
</template>
