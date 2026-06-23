<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ChevronLeft, ChevronRight, Check, Loader2 } from 'lucide-vue-next'
import type { WizardProps, WizardStep } from './types'

const props = withDefaults(defineProps<WizardProps>(), {
  initialStep: 0,
  onComplete: undefined,
  onCancel: undefined,
  showProgress: true,
  allowSkip: false,
  submitLabel: 'Complete',
  cancelLabel: 'Cancel',
  nextLabel: 'Next',
  previousLabel: 'Previous',
})

const { t } = useI18n()

const currentStepIndex = ref(props.initialStep)
const isSubmitting = ref(false)
const stepData = ref<Record<string, unknown>>({})

// 计算当前步骤
const currentStep = computed(() => props.steps[currentStepIndex.value])

// 计算进度百分比
const progress = computed(() => {
  return ((currentStepIndex.value + 1) / props.steps.length) * 100
})

// 计算是否是第一步
const isFirstStep = computed(() => currentStepIndex.value === 0)

// 计算是否是最后一步
const isLastStep = computed(() => currentStepIndex.value === props.steps.length - 1)

// 验证当前步骤
async function validateCurrentStep(): Promise<boolean> {
  const step = currentStep.value
  if (!step.validation) return true

  try {
    return await step.validation()
  } catch (error) {
    console.error('Step validation failed:', error)
    return false
  }
}

// 下一步
async function nextStep() {
  const isValid = await validateCurrentStep()
  if (!isValid) return

  if (isLastStep.value) {
    await completeWizard()
  } else {
    currentStepIndex.value++
  }
}

// 上一步
function previousStep() {
  if (isFirstStep.value) return
  currentStepIndex.value--
}

// 跳过当前步骤
function skipStep() {
  if (!props.allowSkip || isLastStep.value) return
  currentStepIndex.value++
}

// 完成向导
async function completeWizard() {
  isSubmitting.value = true
  try {
    await props.onComplete?.(stepData.value)
  } finally {
    isSubmitting.value = false
  }
}

// 取消向导
function cancelWizard() {
  props.onCancel?.()
}

// 更新步骤数据
function updateStepData(data: Record<string, unknown>) {
  stepData.value = { ...stepData.value, ...data }
}

// 监听步骤变化
watch(currentStepIndex, (newIndex, oldIndex) => {
  // 可以在这里添加步骤切换的动画或其他逻辑
})
</script>

<template>
  <Card class="w-full max-w-2xl mx-auto">
    <CardHeader>
      <div class="flex items-center justify-between">
        <div>
          <CardTitle>{{ currentStep.title }}</CardTitle>
          <CardDescription v-if="currentStep.description">
            {{ currentStep.description }}
          </CardDescription>
        </div>
        <Badge variant="outline">
          {{ t('wizard.step', { current: currentStepIndex + 1, total: steps.length }) }}
        </Badge>
      </div>

      <!-- 进度条 -->
      <Progress v-if="showProgress" :value="progress" class="mt-4" />
    </CardHeader>

    <CardContent>
      <!-- 步骤内容 -->
      <div class="min-h-[300px]">
        <component
          :is="currentStep.component"
          v-bind="currentStep.props"
          :data="stepData"
          @update="updateStepData"
        />
      </div>

      <!-- 步骤指示器 -->
      <div class="flex items-center justify-center gap-2 mt-6">
        <div
          v-for="(step, index) in steps"
          :key="step.id"
          class="flex items-center gap-2"
        >
          <div
            class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium"
            :class="{
              'bg-primary text-primary-foreground': index === currentStepIndex,
              'bg-primary/20 text-primary': index < currentStepIndex,
              'bg-muted text-muted-foreground': index > currentStepIndex,
            }"
          >
            <Check v-if="index < currentStepIndex" class="h-4 w-4" />
            <span v-else>{{ index + 1 }}</span>
          </div>
          <div
            v-if="index < steps.length - 1"
            class="w-8 h-0.5"
            :class="{
              'bg-primary': index < currentStepIndex,
              'bg-muted': index >= currentStepIndex,
            }"
          />
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex items-center justify-between mt-6">
        <div class="flex items-center gap-2">
          <Button
            v-if="onCancel"
            variant="ghost"
            @click="cancelWizard"
          >
            {{ cancelLabel }}
          </Button>
          <Button
            v-if="allowSkip && !isLastStep"
            variant="ghost"
            @click="skipStep"
          >
            {{ t('wizard.skip') }}
          </Button>
        </div>

        <div class="flex items-center gap-2">
          <Button
            v-if="!isFirstStep"
            variant="outline"
            @click="previousStep"
          >
            <ChevronLeft class="h-4 w-4 mr-2" />
            {{ previousLabel }}
          </Button>
          <Button
            @click="nextStep"
            :disabled="isSubmitting"
          >
            <Loader2 v-if="isSubmitting" class="h-4 w-4 mr-2 animate-spin" />
            <template v-else>
              {{ isLastStep ? submitLabel : nextLabel }}
              <ChevronRight v-if="!isLastStep" class="h-4 w-4 ml-2" />
            </template>
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
