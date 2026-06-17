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
const { register, isLoading } = useAuth()
const { t } = useI18n()

const email = shallowRef('')
const password = shallowRef('')
const confirmPassword = shallowRef('')
const fullName = shallowRef('')

async function handleRegister() {
  if (password.value !== confirmPassword.value) {
    toast.error(t('auth.passwordMismatch'))
    return
  }

  try {
    await register(email.value, password.value, fullName.value || undefined)
    toast.success(t('auth.registerSuccess'))
    router.push('/')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || t('auth.registerFailed'))
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
          <CardTitle class="text-heading">{{ t('auth.registerTitle') }}</CardTitle>
          <CardDescription>{{ t('auth.registerDesc') }}</CardDescription>
        </CardHeader>
        <CardContent class="pt-2">
          <form @submit.prevent="handleRegister" class="space-y-5">
            <div class="space-y-2">
              <Label for="fullName">{{ t('auth.fullName') }}</Label>
              <Input id="fullName" v-model="fullName" type="text" :placeholder="t('auth.fullNamePlaceholder')" />
            </div>

            <div class="space-y-2">
              <Label for="email">{{ t('auth.email') }}</Label>
              <Input id="email" v-model="email" type="email" required placeholder="your@email.com" />
            </div>

            <div class="space-y-2">
              <Label for="password">{{ t('auth.password') }}</Label>
              <Input id="password" v-model="password" type="password" required minlength="8" :placeholder="t('auth.passwordMin')" />
            </div>

            <div class="space-y-2">
              <Label for="confirmPassword">{{ t('auth.confirmPassword') }}</Label>
              <Input id="confirmPassword" v-model="confirmPassword" type="password" required minlength="8" :placeholder="t('auth.confirmPasswordPlaceholder')" />
            </div>

            <Button type="submit" class="w-full h-10 rounded-[var(--radius-lg)]" :disabled="isLoading">
              {{ isLoading ? t('auth.registering') : t('auth.register') }}
            </Button>
          </form>

          <p class="mt-6 text-center text-sm text-muted-foreground">
            {{ t('auth.hasAccount') }}
            <router-link to="/login" class="text-foreground font-medium hover:underline underline-offset-2">{{ t('auth.login') }}</router-link>
          </p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
