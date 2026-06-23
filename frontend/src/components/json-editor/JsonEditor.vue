<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Copy, Check, Code, Braces, TreePine, AlertCircle } from 'lucide-vue-next'
import type { JsonEditorProps } from './types'

const props = withDefaults(defineProps<JsonEditorProps>(), {
  modelValue: undefined,
  placeholder: 'Enter JSON...',
  minHeight: '200px',
  maxHeight: '500px',
  readonly: false,
  disabled: false,
  showToolbar: true,
  showCopy: true,
  showFormat: true,
  showValidate: true,
  showTree: false,
  indent: 2,
  onUpdate: undefined,
  onError: undefined,
  onCopy: undefined,
})

const { t } = useI18n()

const content = ref('')
const copied = ref(false)
const isValid = ref(true)
const error = ref<string | null>(null)
const showTreeView = ref(false)

// 计算编辑器样式
const editorStyle = computed(() => {
  return {
    minHeight: typeof props.minHeight === 'number' ? `${props.minHeight}px` : props.minHeight,
    maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight,
  }
})

// 计算 JSON 字符串
const jsonString = computed(() => {
  if (props.modelValue === undefined) return ''
  try {
    return JSON.stringify(props.modelValue, null, props.indent)
  } catch {
    return String(props.modelValue)
  }
})

// 初始化内容
content.value = jsonString.value

// 处理输入
function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  content.value = target.value

  // 验证 JSON
  validateJson(content.value)
}

// 验证 JSON
function validateJson(json: string) {
  if (!json.trim()) {
    isValid.value = true
    error.value = null
    return
  }

  try {
    const parsed = JSON.parse(json)
    isValid.value = true
    error.value = null

    // 触发更新事件
    props.onUpdate?.(parsed)
  } catch (e) {
    isValid.value = false
    error.value = (e as Error).message
    props.onError?.(e as Error)
  }
}

// 格式化 JSON
function formatJson() {
  try {
    const parsed = JSON.parse(content.value)
    content.value = JSON.stringify(parsed, null, props.indent)
    props.onUpdate?.(parsed)
  } catch (e) {
    error.value = (e as Error).message
    props.onError?.(e as Error)
  }
}

// 压缩 JSON
function compressJson() {
  try {
    const parsed = JSON.parse(content.value)
    content.value = JSON.stringify(parsed)
    props.onUpdate?.(parsed)
  } catch (e) {
    error.value = (e as Error).message
    props.onError?.(e as Error)
  }
}

// 复制 JSON
async function copyJson() {
  try {
    await navigator.clipboard.writeText(content.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
    props.onCopy?.(content.value)
  } catch (error) {
    console.error('Failed to copy:', error)
  }
}

// 切换树形视图
function toggleTreeView() {
  showTreeView.value = !showTreeView.value
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue === undefined) {
      content.value = ''
    } else {
      try {
        const newJson = JSON.stringify(newValue, null, props.indent)
        if (newJson !== content.value) {
          content.value = newJson
        }
      } catch {
        content.value = String(newValue)
      }
    }
  },
  { deep: true }
)
</script>

<template>
  <Card>
    <CardHeader v-if="showToolbar" class="flex flex-row items-center justify-between space-y-0 py-2 px-4 bg-muted/50">
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium">JSON</span>
        <Badge
          :variant="isValid ? 'default' : 'destructive'"
          class="text-xs"
        >
          {{ isValid ? t('json.valid') : t('json.invalid') }}
        </Badge>
      </div>
      <div class="flex items-center gap-1">
        <Button
          v-if="showCopy"
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="copyJson"
        >
          <Check v-if="copied" class="h-4 w-4 text-green-500" />
          <Copy v-else class="h-4 w-4" />
        </Button>
        <Button
          v-if="showFormat"
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="formatJson"
        >
          <Code class="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="compressJson"
        >
          <Braces class="h-4 w-4" />
        </Button>
        <Button
          v-if="showTree"
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="toggleTreeView"
        >
          <TreePine class="h-4 w-4" />
        </Button>
      </div>
    </CardHeader>
    <CardContent class="p-0">
      <!-- 编辑器 -->
      <div class="relative">
        <Textarea
          :value="content"
          :placeholder="placeholder"
          :readonly="readonly"
          :disabled="disabled"
          class="resize-none font-mono text-sm focus:outline-none"
          :class="{
            'opacity-50 cursor-not-allowed': disabled,
            'cursor-default': readonly,
            'border-destructive': !isValid,
          }"
          :style="editorStyle"
          @input="handleInput"
        />
      </div>

      <!-- 错误信息 -->
      <div
        v-if="error"
        class="flex items-center gap-2 px-4 py-2 bg-destructive/10 text-destructive text-sm"
      >
        <AlertCircle class="h-4 w-4" />
        <span>{{ error }}</span>
      </div>
    </CardContent>
  </Card>
</template>
