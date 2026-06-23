<script setup lang="ts">
import { computed } from 'vue'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { CalendarIcon, Upload } from 'lucide-vue-next'
import { format } from 'date-fns'
import type { FormFieldProps } from './types'

const props = defineProps<FormFieldProps>()

// 计算是否有错误
const hasError = computed(() => !!props.error)

// 处理值变化
function handleChange(value: unknown) {
  props.onChange(value)
}
</script>

<template>
  <div class="space-y-2">
    <Label :for="field.name" :class="{ 'text-destructive': hasError }">
      {{ field.label }}
      <span v-if="field.required" class="text-destructive">*</span>
    </Label>

    <!-- 文本输入 -->
    <Input
      v-if="field.type === 'text' || field.type === 'email' || field.type === 'password'"
      :id="field.name"
      :type="field.type"
      :placeholder="field.placeholder"
      :disabled="field.disabled || disabled"
      :value="value as string"
      @input="handleChange(($event.target as HTMLInputElement).value)"
      @blur="onBlur"
      :class="{ 'border-destructive': hasError }"
    />

    <!-- 数字输入 -->
    <Input
      v-else-if="field.type === 'number'"
      :id="field.name"
      type="number"
      :placeholder="field.placeholder"
      :disabled="field.disabled || disabled"
      :value="value as number"
      @input="handleChange(Number(($event.target as HTMLInputElement).value))"
      @blur="onBlur"
      :min="field.validation?.min"
      :max="field.validation?.max"
      :class="{ 'border-destructive': hasError }"
    />

    <!-- 文本域 -->
    <Textarea
      v-else-if="field.type === 'textarea'"
      :id="field.name"
      :placeholder="field.placeholder"
      :disabled="field.disabled || disabled"
      :value="value as string"
      @input="handleChange(($event.target as HTMLTextAreaElement).value)"
      @blur="onBlur"
      :minlength="field.validation?.minLength"
      :maxlength="field.validation?.maxLength"
      :class="{ 'border-destructive': hasError }"
    />

    <!-- 下拉选择 -->
    <Select
      v-else-if="field.type === 'select'"
      :value="value as string"
      @update:value="handleChange"
      :disabled="field.disabled || disabled"
    >
      <SelectTrigger :class="{ 'border-destructive': hasError }">
        <SelectValue :placeholder="field.placeholder" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem
          v-for="option in field.options"
          :key="option.value"
          :value="option.value.toString()"
        >
          {{ option.label }}
        </SelectItem>
      </SelectContent>
    </Select>

    <!-- 复选框 -->
    <div v-else-if="field.type === 'checkbox'" class="flex items-center space-x-2">
      <Checkbox
        :id="field.name"
        :checked="value as boolean"
        @update:checked="handleChange"
        :disabled="field.disabled || disabled"
      />
      <Label :for="field.name" class="text-sm font-normal">
        {{ field.description }}
      </Label>
    </div>

    <!-- 单选框 -->
    <RadioGroup
      v-else-if="field.type === 'radio'"
      :value="value as string"
      @update:value="handleChange"
      :disabled="field.disabled || disabled"
    >
      <div v-for="option in field.options" :key="option.value" class="flex items-center space-x-2">
        <RadioGroupItem :value="option.value.toString()" :id="`${field.name}-${option.value}`" />
        <Label :for="`${field.name}-${option.value}`" class="text-sm font-normal">
          {{ option.label }}
        </Label>
      </div>
    </RadioGroup>

    <!-- 日期选择 -->
    <Popover v-else-if="field.type === 'date'">
      <PopoverTrigger as-child>
        <Button
          variant="outline"
          :class="[
            'w-full justify-start text-left font-normal',
            !value && 'text-muted-foreground',
            hasError && 'border-destructive',
          ]"
          :disabled="field.disabled || disabled"
        >
          <CalendarIcon class="mr-2 h-4 w-4" />
          {{ value ? format(new Date(value as string), 'PPP') : field.placeholder }}
        </Button>
      </PopoverTrigger>
      <PopoverContent class="w-auto p-0">
        <Calendar
          :model-value="value ? new Date(value as string) : undefined"
          @update:model-value="handleChange"
        />
      </PopoverContent>
    </Popover>

    <!-- 文件上传 -->
    <div v-else-if="field.type === 'file'" class="flex items-center gap-2">
      <Button
        variant="outline"
        :disabled="field.disabled || disabled"
        @click="($refs.fileInput as HTMLInputElement)?.click()"
      >
        <Upload class="mr-2 h-4 w-4" />
        {{ field.placeholder || 'Choose file' }}
      </Button>
      <input
        ref="fileInput"
        type="file"
        class="hidden"
        :disabled="field.disabled || disabled"
        @change="handleChange(($event.target as HTMLInputElement).files?.[0])"
      />
      <span v-if="value" class="text-sm text-muted-foreground">
        {{ (value as File).name }}
      </span>
    </div>

    <!-- 字段描述 -->
    <p v-if="field.description && field.type !== 'checkbox'" class="text-sm text-muted-foreground">
      {{ field.description }}
    </p>

    <!-- 错误信息 -->
    <p v-if="hasError" class="text-sm text-destructive">
      {{ error }}
    </p>
  </div>
</template>
