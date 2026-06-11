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
const { login, isLoading } = useAuth()

const email = ref('')
const password = ref('')

async function handleLogin() {
  try {
    await login(email.value, password.value)
    toast.success('登录成功')
    router.push('/')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || '登录失败，请重试')
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-muted/30 p-4">
    <Card class="w-full max-w-md">
      <CardHeader class="text-center">
        <CardTitle class="text-2xl">Academic Cluster</CardTitle>
        <CardDescription>登录到您的账户</CardDescription>
      </CardHeader>
      <CardContent>
        <form @submit.prevent="handleLogin" class="space-y-4">
          <div class="space-y-2">
            <Label for="email">邮箱</Label>
            <Input id="email" v-model="email" type="email" required placeholder="your@email.com" />
          </div>

          <div class="space-y-2">
            <Label for="password">密码</Label>
            <Input id="password" v-model="password" type="password" required minlength="8" placeholder="至少 8 位" />
          </div>

          <Button type="submit" class="w-full" :disabled="isLoading">
            {{ isLoading ? '登录中...' : '登录' }}
          </Button>
        </form>

        <p class="mt-4 text-center text-sm text-muted-foreground">
          还没有账户？
          <router-link to="/register" class="text-primary hover:underline">注册</router-link>
        </p>
      </CardContent>
    </Card>
  </div>
</template>
