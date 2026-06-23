<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { toast } from 'vue-sonner'
import { CreditCard, Download, Check, Zap, Building2 } from 'lucide-vue-next'
import type { BillingProps, Plan } from './types'

const props = withDefaults(defineProps<BillingProps>(), {
  onPlanSelect: undefined,
  onPaymentUpdate: undefined,
  onInvoiceDownload: undefined,
})

const { t } = useI18n()

const currentPlanId = ref(props.currentPlanId)

// 计算当前套餐
const currentPlan = computed(() => {
  return props.plans.find((p) => p.id === currentPlanId.value)
})

// 选择套餐
function selectPlan(planId: string) {
  const plan = props.plans.find((p) => p.id === planId)
  if (!plan) return

  currentPlanId.value = planId
  props.onPlanSelect?.(planId)
  toast.success(t('billing.planChanged', { plan: plan.name }))
}

// 获取套餐图标
function getPlanIcon(plan: Plan) {
  if (plan.id === 'enterprise') return Building2
  if (plan.featured) return Zap
  return Check
}

// 获取发票状态颜色
function getInvoiceStatusColor(status: string) {
  switch (status) {
    case 'paid':
      return 'bg-green-100 text-green-800'
    case 'open':
      return 'bg-yellow-100 text-yellow-800'
    case 'void':
      return 'bg-gray-100 text-gray-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}

// 格式化金额
function formatAmount(amount: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(amount)
}

// 下载发票
function downloadInvoice(invoiceId: string) {
  props.onInvoiceDownload?.(invoiceId)
  toast.success(t('billing.invoiceDownloaded'))
}
</script>

<template>
  <div class="space-y-8">
    <!-- 当前套餐卡片 -->
    <Card>
      <CardHeader>
        <div class="flex items-center justify-between">
          <div>
            <CardTitle>{{ t('billing.currentPlan') }}</CardTitle>
            <CardDescription>{{ currentPlan?.description }}</CardDescription>
          </div>
          <Button variant="outline" size="sm">
            {{ t('billing.manageSubscription') }}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div v-for="metric in usageMetrics" :key="metric.label" class="space-y-2">
            <div class="text-sm font-medium text-muted-foreground">{{ metric.label }}</div>
            <div class="flex items-baseline gap-1">
              <span class="text-2xl font-bold">{{ metric.used.toLocaleString() }}</span>
              <span class="text-muted-foreground">/ {{ metric.limit.toLocaleString() }} {{ metric.unit }}</span>
            </div>
            <div class="h-2 rounded-full bg-muted">
              <div
                class="h-full rounded-full bg-primary"
                :style="{ width: `${Math.min(100, (metric.used / metric.limit) * 100)}%` }"
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 套餐选择器 -->
    <div>
      <h3 class="text-lg font-medium mb-4">{{ t('billing.availablePlans') }}</h3>
      <div class="grid gap-4 md:grid-cols-3">
        <Card
          v-for="plan in plans"
          :key="plan.id"
          class="relative"
          :class="{ 'border-primary': plan.id === currentPlanId }"
        >
          <CardHeader>
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <component :is="getPlanIcon(plan)" class="h-5 w-5" />
                <CardTitle class="text-lg">{{ plan.name }}</CardTitle>
              </div>
              <Badge v-if="plan.featured" variant="default">
                {{ t('billing.popular') }}
              </Badge>
            </div>
            <CardDescription>{{ plan.description }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div class="flex items-baseline gap-1">
              <span class="text-3xl font-bold">{{ formatAmount(plan.price) }}</span>
              <span class="text-muted-foreground">/{{ plan.cadence }}</span>
            </div>

            <ul class="space-y-2">
              <li v-for="feature in plan.features" :key="feature" class="flex items-center gap-2">
                <Check class="h-4 w-4 text-primary" />
                <span class="text-sm">{{ feature }}</span>
              </li>
            </ul>

            <Button
              class="w-full"
              :variant="plan.id === currentPlanId ? 'outline' : 'default'"
              :disabled="plan.id === currentPlanId"
              @click="selectPlan(plan.id)"
            >
              {{ plan.id === currentPlanId ? t('billing.currentPlan') : t('billing.selectPlan') }}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- 支付方式 -->
    <Card v-if="paymentMethod">
      <CardHeader>
        <div class="flex items-center justify-between">
          <div>
            <CardTitle>{{ t('billing.paymentMethod') }}</CardTitle>
            <CardDescription>{{ t('billing.paymentMethodDesc') }}</CardDescription>
          </div>
          <Button variant="outline" size="sm" @click="onPaymentUpdate">
            {{ t('billing.updatePayment') }}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div class="flex items-center gap-4">
          <CreditCard class="h-8 w-8 text-muted-foreground" />
          <div>
            <div class="font-medium">
              {{ paymentMethod.type }} ending in {{ paymentMethod.last4 }}
            </div>
            <div class="text-sm text-muted-foreground">
              Expires {{ paymentMethod.expiry }}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 发票列表 -->
    <Card>
      <CardHeader>
        <CardTitle>{{ t('billing.invoices') }}</CardTitle>
        <CardDescription>{{ t('billing.invoicesDesc') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="space-y-4">
          <div
            v-for="invoice in invoices"
            :key="invoice.id"
            class="flex items-center justify-between py-3 border-b last:border-0"
          >
            <div class="flex items-center gap-4">
              <div>
                <div class="font-medium">{{ invoice.date }}</div>
                <div class="text-sm text-muted-foreground">{{ invoice.id }}</div>
              </div>
              <Badge :class="getInvoiceStatusColor(invoice.status)">
                {{ t(`billing.status.${invoice.status}`) }}
              </Badge>
            </div>
            <div class="flex items-center gap-4">
              <span class="font-medium">{{ formatAmount(invoice.amount) }}</span>
              <Button
                v-if="invoice.downloadUrl"
                variant="ghost"
                size="sm"
                @click="downloadInvoice(invoice.id)"
              >
                <Download class="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
