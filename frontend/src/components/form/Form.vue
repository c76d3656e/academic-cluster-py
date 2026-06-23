<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Loader2 } from 'lucide-vue-next'
import FormFieldComponent from './FormField.vue'
import type { FormProps, FormField } from './types'

const props = withDefaults(defineProps<FormProps>(), {
  initialValues: () => ({}),
  onSubmit: undefined,
  onCancel: undefined,
  submitLabel: 'Submit',
  cancelLabel: 'Cancel',
  isLoading: false,
  disabled: false,
})

const { t } = useI18n()

// 表单值
const values = reactive<Record<string, unknown>>({ ...props.initialValues })

// 表单错误
const errors = reactive<Record<string, string>>({})

// 触摸状态
const touched = reactive<Record<string, boolean>>({})

// 计算是否有错误
const hasErrors = computed(() => {
  return Object.values(errors).some((error) => !!error)
})

// 验证单个字段
function validateField(field: FormField): string | null {
  const value = values[field.name]

  // 必填验证
  if (field.required && (value === undefined || value === null || value === '')) {
    return t('form.required')
  }

  // 如果值为空，跳过其他验证
  if (value === undefined || value === null || value === '') {
    return null
  }

  const validation = field.validation
  if (!validation) return null

  // 最小值验证
  if (validation.min !== undefined && typeof value === 'number' && value < validation.min) {
    return validation.message || t('form.min', { min: validation.min })
  }

  // 最大值验证
  if (validation.max !== undefined && typeof value === 'number' && value > validation.max) {
    return validation.message || t('form.max', { max: validation.max })
  }

  // 最小长度验证
  if (validation.minLength !== undefined && typeof value === 'string' && value.length < validation.minLength) {
    return validation.message || t('form.minLength', { min: validation.minLength })
  }

  // 最大长度验证
  if (validation.maxLength !== undefined && typeof value === 'string' && value.length > validation.maxLength) {
    return validation.message || t('form.maxLength', { max: validation.maxLength })
  }

  // 正则表达式验证
  if (validation.pattern && typeof value === 'string' && !new RegExp(validation.pattern).test(value)) {
    return validation.message || t('form.pattern')
  }

  return null
}

// 验证所有字段
function validateAll(): boolean {
  let isValid = true

  for (const field of props.fields) {
    const error = validateField(field)
    if (error) {
      errors[field.name] = error
      isValid = false
    } else {
      delete errors[field.name]
    }
  }

  return isValid
}

// 处理字段值变化
function handleFieldChange(fieldName: string, value: unknown) {
  values[fieldName] = value

  // 如果字段已被触摸，验证它
  if (touched[fieldName]) {
    const field = props.fields.find((f) => f.name === fieldName)
    if (field) {
      const error = validateField(field)
      if (error) {
        errors[fieldName] = error
      } else {
        delete errors[fieldName]
      }
    }
  }
}

// 处理字段失焦
function handleFieldBlur(fieldName: string) {
  touched[fieldName] = true

  const field = props.fields.find((f) => f.name === fieldName)
  if (field) {
    const error = validateField(field)
    if (error) {
      errors[fieldName] = error
    } else {
      delete errors[fieldName]
    }
  }
}

// 处理表单提交
function handleSubmit() {
  // 标记所有字段为已触摸
  for (const field of props.fields) {
    touched[field.name] = true
  }

  // 验证所有字段
  if (!validateAll()) {
    return
  }

  // 提交表单
  props.onSubmit?.({ ...values })
}

// 处理表单取消
function handleCancel() {
  props.onCancel?.()
}

// 监听初始值变化
watch(
  () => props.initialValues,
  (newValues) => {
    Object.assign(values, newValues)
  },
  { deep: true }
)
</script>

<template>
  <form @submit.prevent="handleSubmit" class="space-y-6">
    <FormFieldComponent
      v-for="field in fields"
      :key="field.name"
      :field="field"
      :value="values[field.name]"
      :error="errors[field.name]"
      :disabled="disabled || isLoading"
      @change="handleFieldChange(field.name, $event)"
      @blur="handleFieldBlur(field.name)"
    />

    <div class="flex items-center justify-end gap-4">
      <Button
        v-if="onCancel"
        type="button"
        variant="outline"
        :disabled="isLoading"
        @click="handleCancel"
      >
        {{ cancelLabel }}
      </Button>
      <Button
        type="submit"
        :disabled="disabled || isLoading || hasErrors"
      >
        <Loader2 v-if="isLoading" class="mr-2 h-4 w-4 animate-spin" />
        {{ submitLabel }}
      </Button>
    </div>
  </form>
</template>
