<script setup lang="ts">
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { toast } from 'vue-sonner'
import type { SocialLoginProps } from './types'

const props = withDefaults(defineProps<SocialLoginProps>(), {
  onLogin: undefined,
  disabled: false,
})

const { t } = useI18n()

// 处理社交登录
function handleSocialLogin(providerId: string) {
  const provider = props.providers.find((p) => p.id === providerId)
  if (!provider || !provider.enabled) {
    toast.error(t('socialLogin.providerNotConfigured'))
    return
  }

  props.onLogin?.(providerId)
}

// 获取提供商图标（这里使用简单的 SVG 占位符）
function getProviderIcon(icon: string) {
  // 在实际应用中，这里应该返回真实的图标组件
  // 这里返回一个简单的占位符
  return icon
}
</script>

<template>
  <div class="space-y-4">
    <div class="relative">
      <div class="absolute inset-0 flex items-center">
        <Separator class="w-full" />
      </div>
      <div class="relative flex justify-center text-xs uppercase">
        <span class="bg-background px-2 text-muted-foreground">
          {{ t('socialLogin.continueWith') }}
        </span>
      </div>
    </div>

    <div class="grid gap-2">
      <Button
        v-for="provider in providers"
        :key="provider.id"
        variant="outline"
        class="w-full"
        :disabled="disabled || !provider.enabled"
        @click="handleSocialLogin(provider.id)"
      >
        <div class="flex items-center gap-2">
          <div
            class="h-5 w-5 rounded-full flex items-center justify-center text-white text-xs font-bold"
            :style="{ backgroundColor: provider.color }"
          >
            {{ getProviderIcon(provider.icon) }}
          </div>
          <span>{{ t(`socialLogin.providers.${provider.id}`) }}</span>
        </div>
      </Button>
    </div>

    <div class="text-center text-xs text-muted-foreground">
      {{ t('socialLogin.terms') }}
    </div>
  </div>
</template>
