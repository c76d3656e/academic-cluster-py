<script setup lang="ts">
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

const { t } = useI18n()
</script>

<template>
  <div class="p-4 md:p-8 max-w-lg">
    <h2 class="text-heading font-medium tracking-tight mb-8">{{ t('console.recharge') }}</h2>

    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-base">{{ t('console.accountBalance') }}</CardTitle>
      </CardHeader>
      <CardContent>
        <p class="text-3xl font-semibold tracking-tight mb-4">--</p>
        <p class="text-sm text-muted-foreground mb-6">{{ t('console.rechargeDesc') }}</p>
        <Button disabled>{{ t('console.rechargeNotOpen') }}</Button>
      </CardContent>
    </Card>
  </div>
</template>
