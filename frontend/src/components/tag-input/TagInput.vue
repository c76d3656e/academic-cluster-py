<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X, Plus } from 'lucide-vue-next'
import type { TagInputProps } from './types'

const props = withDefaults(defineProps<TagInputProps>(), {
  modelValue: () => [],
  placeholder: 'Add tag...',
  disabled: false,
  maxTags: undefined,
  allowDuplicates: false,
  showAddButton: true,
  tagVariant: 'default',
  onUpdate: undefined,
  onChange: undefined,
  onAdd: undefined,
  onRemove: undefined,
})

const { t } = useI18n()

const tags = ref<string[]>(props.modelValue)
const inputValue = ref('')

// 计算是否可以添加新标签
const canAddTag = computed(() => {
  const trimmedValue = inputValue.value.trim()
  if (!trimmedValue) return false
  if (!props.allowDuplicates && tags.value.includes(trimmedValue)) return false
  if (props.maxTags && tags.value.length >= props.maxTags) return false
  return true
})

// 添加标签
function addTag() {
  const trimmedValue = inputValue.value.trim()
  if (!canAddTag.value) return

  tags.value = [...tags.value, trimmedValue]
  inputValue.value = ''
  emitChange()
  props.onAdd?.(trimmedValue)
}

// 移除标签
function removeTag(tag: string) {
  tags.value = tags.value.filter((t) => t !== tag)
  emitChange()
  props.onRemove?.(tag)
}

// 处理按键
function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    addTag()
  } else if (event.key === 'Backspace' && !inputValue.value && tags.value.length > 0) {
    removeTag(tags.value[tags.value.length - 1])
  }
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(tags.value)
  props.onChange?.(tags.value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    tags.value = newValue
  }
)
</script>

<template>
  <div class="space-y-2">
    <!-- 标签列表 -->
    <div
      v-if="tags.length > 0"
      class="flex flex-wrap gap-2"
    >
      <Badge
        v-for="tag in tags"
        :key="tag"
        :variant="tagVariant"
        class="flex items-center gap-1"
      >
        <span>{{ tag }}</span>
        <Button
          v-if="!disabled"
          variant="ghost"
          size="sm"
          class="h-4 w-4 p-0 hover:bg-transparent"
          @click="removeTag(tag)"
        >
          <X class="h-3 w-3" />
        </Button>
      </Badge>
    </div>

    <!-- 输入框 -->
    <div class="flex items-center gap-2">
      <Input
        v-model="inputValue"
        :placeholder="placeholder"
        :disabled="disabled"
        class="flex-1"
        @keydown="handleKeydown"
      />
      <Button
        v-if="showAddButton"
        variant="outline"
        size="sm"
        :disabled="!canAddTag || disabled"
        @click="addTag"
      >
        <Plus class="h-4 w-4" />
      </Button>
    </div>

    <!-- 提示信息 -->
    <div
      v-if="maxTags"
      class="text-sm text-muted-foreground"
    >
      {{ t('tagInput.maxTags', { max: maxTags, current: tags.length }) }}
    </div>
  </div>
</template>
