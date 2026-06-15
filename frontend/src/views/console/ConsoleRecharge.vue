<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
</script>

<template>
  <div class="p-8 max-w-lg">
    <h2 class="text-heading font-medium tracking-tight mb-8">充值</h2>

    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-base">账户余额</CardTitle>
      </CardHeader>
      <CardContent>
        <p class="text-3xl font-semibold tracking-tight mb-4">--</p>
        <p class="text-sm text-muted-foreground mb-6">在线充值功能暂未开放，敬请期待。</p>
        <Button disabled>充值（暂未开放）</Button>
      </CardContent>
    </Card>
  </div>
</template>
