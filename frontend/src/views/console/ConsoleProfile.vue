<script setup lang="ts">
import { shallowRef } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from '@/i18n'
import { consoleApi } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'vue-sonner'

const { user } = useAuth()
const { t } = useI18n()

const fullName = shallowRef(user?.full_name || '')
const currentPassword = shallowRef('')
const newPassword = shallowRef('')
const confirmPassword = shallowRef('')
const isSaving = shallowRef(false)
const isChangingPassword = shallowRef(false)

async function saveProfile() {
  isSaving.value = true
  try {
    await consoleApi.updateProfile({ full_name: fullName.value })
    toast.success(t('console.profileUpdated'))
  } catch {
    toast.error(t('console.profileUpdateFailed'))
  } finally {
    isSaving.value = false
  }
}

async function changePassword() {
  if (newPassword.value !== confirmPassword.value) {
    toast.error(t('auth.passwordMismatch'))
    return
  }
  if (newPassword.value.length < 6) {
    toast.error(t('auth.passwordMinLength'))
    return
  }
  isChangingPassword.value = true
  try {
    await consoleApi.changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    toast.success(t('auth.passwordChanged'))
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch {
    toast.error(t('auth.changePasswordFailed'))
  } finally {
    isChangingPassword.value = false
  }
}
</script>

<template>
  <div class="p-4 md:p-8 max-w-2xl">
    <h2 class="text-heading font-medium tracking-tight mb-8">{{ t('console.profile') }}</h2>

    <!-- Account Info -->
    <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
      <CardHeader>
        <CardTitle class="text-base">{{ t('console.accountInfo') }}</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <div>
          <Label class="text-caption text-muted-foreground">{{ t('auth.email') }}</Label>
          <p class="text-sm mt-1">{{ user?.email }}</p>
        </div>
        <div>
          <Label class="text-caption text-muted-foreground">{{ t('auth.role') }}</Label>
          <p class="text-sm mt-1">{{ user?.role }}</p>
        </div>
        <div>
          <Label for="fullName" class="text-caption text-muted-foreground">{{ t('auth.nickname') }}</Label>
          <Input id="fullName" v-model="fullName" class="mt-1" :placeholder="t('auth.nicknamePlaceholder')" />
        </div>
        <Button @click="saveProfile" :disabled="isSaving" size="sm">
          {{ isSaving ? t('common.saving') : t('common.save') }}
        </Button>
      </CardContent>
    </Card>

    <!-- Change Password -->
    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-base">{{ t('auth.changePassword') }}</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <div>
          <Label for="currentPwd" class="text-caption text-muted-foreground">{{ t('auth.currentPassword') }}</Label>
          <Input id="currentPwd" v-model="currentPassword" type="password" class="mt-1" />
        </div>
        <div>
          <Label for="newPwd" class="text-caption text-muted-foreground">{{ t('auth.newPassword') }}</Label>
          <Input id="newPwd" v-model="newPassword" type="password" class="mt-1" />
        </div>
        <div>
          <Label for="confirmPwd" class="text-caption text-muted-foreground">{{ t('auth.confirmPassword') }}</Label>
          <Input id="confirmPwd" v-model="confirmPassword" type="password" class="mt-1" />
        </div>
        <Button @click="changePassword" :disabled="isChangingPassword" size="sm">
          {{ isChangingPassword ? t('auth.changing') : t('auth.changePassword') }}
        </Button>
      </CardContent>
    </Card>
  </div>
</template>
