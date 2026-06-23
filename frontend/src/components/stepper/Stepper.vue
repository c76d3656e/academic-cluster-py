<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Check, Circle, Loader2, AlertCircle } from 'lucide-vue-next'
import type { StepperProps, Step } from './types'

const props = withDefaults(defineProps<StepperProps>(), {
  onStepClick: undefined,
  variant: 'default',
  size: 'md',
  clickable: false,
  showDescription: true,
})

const { t } = useI18n()

// 计算步骤状态
function getStepStatus(step: Step, index: number): string {
  if (step.status) return step.status
  if (index < props.currentStep) return 'completed'
  if (index === props.currentStep) return 'active'
  return 'pending'
}

// 计算步骤图标
function getStepIcon(step: Step, index: number) {
  const status = getStepStatus(step, index)

  if (status === 'completed') return Check
  if (status === 'error') return AlertCircle
  if (status === 'active') return Loader2
  return Circle
}

// 计算步骤样式
function getStepClass(step: Step, index: number): string {
  const status = getStepStatus(step, index)
  const classes: string[] = []

  switch (status) {
    case 'completed':
      classes.push('text-primary')
      break
    case 'active':
      classes.push('text-primary')
      break
    case 'error':
      classes.push('text-destructive')
      break
    case 'pending':
      classes.push('text-muted-foreground')
      break
  }

  return classes.join(' ')
}

// 计算连接线样式
function getConnectorClass(index: number): string {
  if (index < props.currentStep) {
    return 'bg-primary'
  }
  return 'bg-muted'
}

// 处理步骤点击
function handleStepClick(index: number) {
  if (!props.clickable) return
  props.onStepClick?.(index)
}
</script>

<template>
  <div
    class="flex"
    :class="{
      'flex-col': variant === 'vertical',
      'items-start': variant === 'vertical',
      'items-center': variant !== 'vertical',
    }"
  >
    <template v-for="(step, index) in steps" :key="step.id">
      <!-- 步骤项 -->
      <div
        class="flex items-center gap-3"
        :class="{
          'flex-col': variant === 'dots',
          'cursor-pointer': clickable,
        }"
        @click="handleStepClick(index)"
      >
        <!-- 步骤图标 -->
        <div
          class="flex items-center justify-center rounded-full border-2"
          :class="[
            getStepClass(step, index),
            {
              'w-8 h-8': size === 'sm',
              'w-10 h-10': size === 'md',
              'w-12 h-12': size === 'lg',
              'border-current': getStepStatus(step, index) !== 'pending',
              'border-muted': getStepStatus(step, index) === 'pending',
              'bg-primary text-primary-foreground': getStepStatus(step, index) === 'completed',
              'bg-primary/10': getStepStatus(step, index) === 'active',
              'bg-destructive/10': getStepStatus(step, index) === 'error',
              'w-3 h-3 border-0': variant === 'dots',
            },
          ]"
        >
          <component
            v-if="variant !== 'dots'"
            :is="getStepIcon(step, index)"
            :class="{
              'h-4 w-4': size === 'sm',
              'h-5 w-5': size === 'md',
              'h-6 w-6': size === 'lg',
              'animate-spin': getStepStatus(step, index) === 'active',
            }"
          />
        </div>

        <!-- 步骤信息 -->
        <div
          v-if="variant !== 'dots'"
          class="flex flex-col"
          :class="{
            'items-center': variant === 'default',
            'items-start': variant === 'vertical',
          }"
        >
          <div
            class="font-medium"
            :class="{
              'text-xs': size === 'sm',
              'text-sm': size === 'md',
              'text-base': size === 'lg',
              'text-primary': getStepStatus(step, index) === 'active',
              'text-muted-foreground': getStepStatus(step, index) === 'pending',
            }"
          >
            {{ step.title }}
          </div>
          <div
            v-if="showDescription && step.description"
            class="text-muted-foreground"
            :class="{
              'text-xs': size === 'sm',
              'text-sm': size === 'md',
              'text-base': size === 'lg',
            }"
          >
            {{ step.description }}
          </div>
        </div>
      </div>

      <!-- 连接线 -->
      <div
        v-if="index < steps.length - 1"
        :class="[
          getConnectorClass(index),
          {
            'flex-1 h-0.5 mx-2': variant === 'default',
            'w-0.5 h-8 ml-4': variant === 'vertical',
            'w-8 h-0.5 mx-1': variant === 'dots',
          },
        ]"
      />
    </template>
  </div>
</template>
