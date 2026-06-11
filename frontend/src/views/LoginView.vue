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
  <div class="min-h-screen flex items-center justify-center bg-background p-4">
    <div class="w-full max-w-md">
      <!-- Brand -->
      <div class="text-center mb-8">
        <h1 class="text-display font-medium tracking-tight">Academic Cluster</h1>
        <p class="text-muted-foreground mt-2 text-body">学术论文聚类分析平台</p>
      </div>

      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="text-center pb-2">
          <CardTitle class="text-heading">登录</CardTitle>
          <CardDescription>登录到您的账户</CardDescription>
        </CardHeader>
        <CardContent class="pt-2">
          <form @submit.prevent="handleLogin" class="space-y-5">
            <div class="space-y-2">
              <Label for="email">邮箱</Label>
              <Input id="email" v-model="email" type="email" required placeholder="your@email.com" />
            </div>

            <div class="space-y-2">
              <Label for="password">密码</Label>
              <Input id="password" v-model="password" type="password" required minlength="8" placeholder="至少 8 位" />
            </div>

            <Button type="submit" class="w-full h-10 rounded-[var(--radius-lg)]" :disabled="isLoading">
              {{ isLoading ? '登录中...' : '登录' }}
            </Button>
          </form>

          <p class="mt-6 text-center text-sm text-muted-foreground">
            还没有账户？
            <router-link to="/register" class="text-foreground font-medium hover:underline underline-offset-2">注册</router-link>
          </p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
