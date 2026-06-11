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
  <div class="min-h-screen flex items-center justify-center bg-background p-4">
    <div class="w-full max-w-md">
      <!-- Brand -->
      <div class="text-center mb-8">
        <h1 class="text-display font-medium tracking-tight">Academic Cluster</h1>
        <p class="text-muted-foreground mt-2 text-body">学术论文聚类分析平台</p>
      </div>

      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="text-center pb-2">
          <CardTitle class="text-heading">注册</CardTitle>
          <CardDescription>创建新账户</CardDescription>
        </CardHeader>
        <CardContent class="pt-2">
          <form @submit.prevent="handleRegister" class="space-y-5">
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

            <Button type="submit" class="w-full h-10 rounded-[var(--radius-lg)]" :disabled="isLoading">
              {{ isLoading ? '注册中...' : '注册' }}
            </Button>
          </form>

          <p class="mt-6 text-center text-sm text-muted-foreground">
            已有账户？
            <router-link to="/login" class="text-foreground font-medium hover:underline underline-offset-2">登录</router-link>
          </p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
