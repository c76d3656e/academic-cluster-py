<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Copy, Check, Code, WrapText, Minus, Plus } from 'lucide-vue-next'
import type { CodeEditorProps } from './types'

const props = withDefaults(defineProps<CodeEditorProps>(), {
  modelValue: '',
  language: 'text',
  theme: 'light',
  placeholder: 'Enter code...',
  minHeight: '200px',
  maxHeight: '500px',
  readonly: false,
  disabled: false,
  showLineNumbers: true,
  showMinimap: false,
  showToolbar: true,
  showCopy: true,
  showFormat: false,
  tabSize: 2,
  wordWrap: 'on',
  fontSize: 14,
  fontFamily: 'monospace',
  onUpdate: undefined,
  onFocus: undefined,
  onBlur: undefined,
  onCopy: undefined,
  onFormat: undefined,
})

const { t } = useI18n()

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const content = ref(props.modelValue)
const copied = ref(false)
const currentFontSize = ref(props.fontSize)

// 计算编辑器样式
const editorStyle = computed(() => {
  return {
    minHeight: typeof props.minHeight === 'number' ? `${props.minHeight}px` : props.minHeight,
    maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight,
    fontSize: `${currentFontSize.value}px`,
    fontFamily: props.fontFamily,
    tabSize: props.tabSize,
    whiteSpace: props.wordWrap === 'on' ? 'pre-wrap' : 'pre',
    wordWrap: props.wordWrap === 'on' ? 'break-word' : 'normal',
  } as const
})

// 计算行号
const lineNumbers = computed(() => {
  const lines = content.value.split('\n')
  return Array.from({ length: lines.length }, (_, i) => i + 1)
})

// 处理输入
function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  content.value = target.value
  props.onUpdate?.(content.value)
}

// 处理焦点
function handleFocus() {
  props.onFocus?.()
}

// 处理失焦
function handleBlur() {
  props.onBlur?.()
}

// 处理按键
function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Tab') {
    event.preventDefault()

    const textarea = textareaRef.value
    if (!textarea) return

    const start = textarea.selectionStart
    const end = textarea.selectionEnd

    // 插入制表符
    const spaces = ' '.repeat(props.tabSize)
    content.value = content.value.substring(0, start) + spaces + content.value.substring(end)

    // 更新光标位置
    setTimeout(() => {
      textarea.selectionStart = textarea.selectionEnd = start + props.tabSize
    })

    props.onUpdate?.(content.value)
  }
}

// 复制代码
async function copyCode() {
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

// 格式化代码
function formatCode() {
  if (props.onFormat) {
    content.value = props.onFormat(content.value)
    props.onUpdate?.(content.value)
  }
}

// 增加字体大小
function increaseFontSize() {
  if (currentFontSize.value < 24) {
    currentFontSize.value++
  }
}

// 减少字体大小
function decreaseFontSize() {
  if (currentFontSize.value > 10) {
    currentFontSize.value--
  }
}

// 切换自动换行
function toggleWordWrap() {
  // 这里可以实现切换自动换行的逻辑
  // 为了简化，这里只是触发一个事件
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue !== content.value) {
      content.value = newValue
    }
  }
)

// 组件挂载时初始化
onMounted(() => {
  content.value = props.modelValue
})
</script>

<template>
  <Card>
    <CardHeader v-if="showToolbar" class="flex flex-row items-center justify-between space-y-0 py-2 px-4 bg-muted/50">
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium">{{ language }}</span>
        <Badge variant="secondary" class="text-xs">
          {{ t('editor.lines') }}: {{ lineNumbers.length }}
        </Badge>
      </div>
      <div class="flex items-center gap-1">
        <Button
          v-if="showCopy"
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="copyCode"
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
          @click="formatCode"
        >
          <Code class="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled"
          @click="toggleWordWrap"
        >
          <WrapText class="h-4 w-4" />
        </Button>
        <div class="flex items-center gap-1 ml-2">
          <Button
            variant="ghost"
            size="sm"
            class="h-8 w-8 p-0"
            :disabled="disabled"
            @click="decreaseFontSize"
          >
            <Minus class="h-4 w-4" />
          </Button>
          <span class="text-sm w-8 text-center">{{ currentFontSize }}</span>
          <Button
            variant="ghost"
            size="sm"
            class="h-8 w-8 p-0"
            :disabled="disabled"
            @click="increaseFontSize"
          >
            <Plus class="h-4 w-4" />
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="p-0">
      <div class="relative">
        <!-- 行号 -->
        <div
          v-if="showLineNumbers"
          class="absolute left-0 top-0 bottom-0 w-12 bg-muted/50 text-muted-foreground text-sm text-right select-none pr-2 py-4 overflow-hidden"
        >
          <div
            v-for="line in lineNumbers"
            :key="line"
            class="leading-relaxed"
          >
            {{ line }}
          </div>
        </div>

        <!-- 代码编辑器 -->
        <textarea
          ref="textareaRef"
          :value="content"
          :placeholder="placeholder"
          :readonly="readonly"
          :disabled="disabled"
          class="w-full resize-none focus:outline-none bg-transparent p-4"
          :class="{
            'pl-16': showLineNumbers,
            'opacity-50 cursor-not-allowed': disabled,
            'cursor-default': readonly,
          }"
          :style="editorStyle"
          @input="handleInput"
          @focus="handleFocus"
          @blur="handleBlur"
          @keydown="handleKeydown"
        />
      </div>
    </CardContent>
  </Card>
</template>
