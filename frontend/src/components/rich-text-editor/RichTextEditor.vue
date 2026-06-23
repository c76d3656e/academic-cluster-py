<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Bold,
  Italic,
  Underline,
  Strikethrough,
  List,
  ListOrdered,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  Link,
  Image,
  Quote,
  Code,
  Undo2,
  Redo2,
  Type,
  Heading1,
  Heading2,
  Heading3,
} from 'lucide-vue-next'
import type { RichTextEditorProps } from './types'

const props = withDefaults(defineProps<RichTextEditorProps>(), {
  modelValue: '',
  placeholder: 'Start typing...',
  minHeight: '200px',
  maxHeight: '500px',
  readonly: false,
  disabled: false,
  showToolbar: true,
  showWordCount: false,
  showCharCount: false,
  maxLength: undefined,
  toolbar: () => [
    'bold',
    'italic',
    'underline',
    'strikethrough',
    'separator',
    'heading1',
    'heading2',
    'heading3',
    'separator',
    'list',
    'ordered-list',
    'separator',
    'align-left',
    'align-center',
    'align-right',
    'align-justify',
    'separator',
    'link',
    'image',
    'quote',
    'code',
    'separator',
    'undo',
    'redo',
  ],
  format: 'html',
  onUpdate: undefined,
  onFocus: undefined,
  onBlur: undefined,
  onPaste: undefined,
})

const { t } = useI18n()

const editorRef = ref<HTMLDivElement | null>(null)
const content = ref(props.modelValue)
const wordCount = ref(0)
const charCount = ref(0)

// 计算编辑器样式
const editorStyle = computed(() => {
  return {
    minHeight: typeof props.minHeight === 'number' ? `${props.minHeight}px` : props.minHeight,
    maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight,
  }
})

// 获取工具栏图标
function getToolbarIcon(tool: string) {
  switch (tool) {
    case 'bold':
      return Bold
    case 'italic':
      return Italic
    case 'underline':
      return Underline
    case 'strikethrough':
      return Strikethrough
    case 'heading1':
      return Heading1
    case 'heading2':
      return Heading2
    case 'heading3':
      return Heading3
    case 'list':
      return List
    case 'ordered-list':
      return ListOrdered
    case 'align-left':
      return AlignLeft
    case 'align-center':
      return AlignCenter
    case 'align-right':
      return AlignRight
    case 'align-justify':
      return AlignJustify
    case 'link':
      return Link
    case 'image':
      return Image
    case 'quote':
      return Quote
    case 'code':
      return Code
    case 'undo':
      return Undo2
    case 'redo':
      return Redo2
    default:
      return Type
  }
}

// 执行命令
function executeCommand(command: string, value?: string) {
  if (props.readonly || props.disabled) return

  document.execCommand(command, false, value)
  updateContent()
}

// 处理工具栏点击
function handleToolbarClick(tool: string) {
  if (tool === 'separator') return

  if (tool === 'link') {
    const url = prompt(t('editor.enterUrl'))
    if (url) {
      executeCommand('createLink', url)
    }
  } else if (tool === 'image') {
    const url = prompt(t('editor.enterImageUrl'))
    if (url) {
      executeCommand('insertImage', url)
    }
  } else if (tool.startsWith('heading')) {
    const level = tool.replace('heading', '')
    executeCommand('formatBlock', `h${level}`)
  } else if (tool === 'quote') {
    executeCommand('formatBlock', 'blockquote')
  } else if (tool === 'code') {
    executeCommand('formatBlock', 'pre')
  } else if (tool === 'list') {
    executeCommand('insertUnorderedList')
  } else if (tool === 'ordered-list') {
    executeCommand('insertOrderedList')
  } else if (tool.startsWith('align-')) {
    const align = tool.replace('align-', '')
    executeCommand(`justify${align.charAt(0).toUpperCase() + align.slice(1)}`)
  } else if (tool === 'undo') {
    executeCommand('undo')
  } else if (tool === 'redo') {
    executeCommand('redo')
  } else {
    executeCommand(tool)
  }
}

// 更新内容
function updateContent() {
  if (!editorRef.value) return

  const newContent = editorRef.value.innerHTML
  content.value = newContent

  // 更新字数统计
  updateCounts(newContent)

  // 触发更新事件
  props.onUpdate?.(newContent)
}

// 更新字数统计
function updateCounts(html: string) {
  // 移除 HTML 标签
  const text = html.replace(/<[^>]*>/g, '')

  // 计算字符数
  charCount.value = text.length

  // 计算字数
  const words = text.trim().split(/\s+/).filter((word) => word.length > 0)
  wordCount.value = words.length
}

// 处理输入
function handleInput() {
  updateContent()
}

// 处理焦点
function handleFocus() {
  props.onFocus?.()
}

// 处理失焦
function handleBlur() {
  props.onBlur?.()
}

// 处理粘贴
function handlePaste(event: ClipboardEvent) {
  props.onPaste?.(event)

  // 清理粘贴的内容
  if (event.clipboardData) {
    const text = event.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
    event.preventDefault()
  }
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue !== content.value) {
      content.value = newValue
      if (editorRef.value) {
        editorRef.value.innerHTML = newValue
      }
      updateCounts(newValue)
    }
  }
)

// 组件挂载时初始化
onMounted(() => {
  if (editorRef.value) {
    editorRef.value.innerHTML = content.value
    updateCounts(content.value)
  }
})
</script>

<template>
  <Card>
    <CardContent class="p-0">
      <!-- 工具栏 -->
      <div
        v-if="showToolbar"
        class="flex items-center gap-1 p-2 border-b bg-muted/50 flex-wrap"
      >
        <template v-for="tool in toolbar" :key="tool">
          <Separator
            v-if="tool === 'separator'"
            orientation="vertical"
            class="h-6 mx-1"
          />
          <Button
            v-else
            variant="ghost"
            size="sm"
            class="w-8 h-8 p-0"
            :disabled="readonly || disabled"
            @click="handleToolbarClick(tool)"
          >
            <component :is="getToolbarIcon(tool)" class="h-4 w-4" />
          </Button>
        </template>
      </div>

      <!-- 编辑器 -->
      <div
        ref="editorRef"
        class="p-4 focus:outline-none"
        :class="{
          'opacity-50 cursor-not-allowed': disabled,
          'cursor-default': readonly,
        }"
        :style="editorStyle"
        contenteditable="true"
        :placeholder="placeholder"
        @input="handleInput"
        @focus="handleFocus"
        @blur="handleBlur"
        @paste="handlePaste"
      />

      <!-- 状态栏 -->
      <div
        v-if="showWordCount || showCharCount || maxLength"
        class="flex items-center justify-between px-4 py-2 border-t bg-muted/50 text-sm text-muted-foreground"
      >
        <div class="flex items-center gap-4">
          <span v-if="showWordCount">
            {{ t('editor.words') }}: {{ wordCount }}
          </span>
          <span v-if="showCharCount">
            {{ t('editor.characters') }}: {{ charCount }}
          </span>
        </div>
        <div v-if="maxLength">
          <Badge
            :variant="charCount > maxLength ? 'destructive' : 'secondary'"
          >
            {{ charCount }}/{{ maxLength }}
          </Badge>
        </div>
      </div>
    </CardContent>
  </Card>
</template>

<style scoped>
[contenteditable]:empty:before {
  content: attr(placeholder);
  color: #9ca3af;
  pointer-events: none;
}

[contenteditable]:focus {
  outline: none;
}
</style>
