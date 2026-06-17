<script setup lang="ts">
import { shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { toast } from 'vue-sonner'

const router = useRouter()
const { login, isLoading } = useAuth()
const { t } = useI18n()

const email = shallowRef('')
const password = shallowRef('')

async function handleLogin() {
  try {
    await login(email.value, password.value)
    toast.success(t('auth.loginSuccess'))
    router.push('/')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || t('auth.loginFailed'))
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background p-4">
    <div class="w-full max-w-md">
      <!-- Brand -->
      <div class="text-center mb-8">
        <h1 class="text-display font-medium tracking-tight">Academic Cluster</h1>
        <p class="text-muted-foreground mt-2 text-body">{{ t('auth.platform') }}</p>
      </div>

      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="text-center pb-2">
          <CardTitle class="text-heading">{{ t('auth.loginTitle') }}</CardTitle>
          <CardDescription>{{ t('auth.loginDesc') }}</CardDescription>
        </CardHeader>
        <CardContent class="pt-2">
          <form @submit.prevent="handleLogin" class="space-y-5">
            <div class="space-y-2">
              <Label for="email">{{ t('auth.email') }}</Label>
              <Input id="email" v-model="email" type="email" required placeholder="your@email.com" />
            </div>

            <div class="space-y-2">
              <Label for="password">{{ t('auth.password') }}</Label>
              <Input id="password" v-model="password" type="password" required minlength="8" :placeholder="t('auth.passwordMin')" />
            </div>

            <Button type="submit" class="w-full h-10 rounded-[var(--radius-lg)]" :disabled="isLoading">
              {{ isLoading ? t('auth.loggingIn') : t('auth.login') }}
            </Button>
          </form>

          <p class="mt-6 text-center text-sm text-muted-foreground">
            {{ t('auth.noAccount') }}
            <router-link to="/register" class="text-foreground font-medium hover:underline underline-offset-2">{{ t('auth.register') }}</router-link>
          </p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
