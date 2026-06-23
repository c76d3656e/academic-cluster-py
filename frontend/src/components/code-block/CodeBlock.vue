<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Copy, Check } from 'lucide-vue-next'
import type { CodeBlockProps } from './types'

const props = withDefaults(defineProps<CodeBlockProps>(), {
  language: 'text',
  title: undefined,
  showLineNumbers: true,
  showCopy: true,
  showHeader: true,
  maxHeight: '400px',
  wrap: false,
  highlightLines: () => [],
  onCopy: undefined,
})

const { t } = useI18n()

const copied = ref(false)

// 计算行号
const lineNumbers = computed(() => {
  const lines = props.code.split('\n')
  return Array.from({ length: lines.length }, (_, i) => i + 1)
})

// 计算代码行
const codeLines = computed(() => {
  return props.code.split('\n')
})

// 计算容器样式
const containerStyle = computed(() => {
  return {
    maxHeight: props.maxHeight,
  }
})

// 计算代码样式
const codeClass = computed(() => {
  const classes: string[] = ['font-mono text-sm']

  if (props.wrap) {
    classes.push('whitespace-pre-wrap break-words')
  } else {
    classes.push('whitespace-pre overflow-x-auto')
  }

  return classes.join(' ')
})

// 复制代码
async function copyCode() {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
    props.onCopy?.(props.code)
  } catch (error) {
    console.error('Failed to copy:', error)
  }
}

// 检查行是否高亮
function isLineHighlighted(lineNumber: number): boolean {
  return props.highlightLines.includes(lineNumber)
}
</script>

<template>
  <Card class="overflow-hidden">
    <CardHeader v-if="showHeader" class="flex flex-row items-center justify-between space-y-0 py-2 px-4 bg-muted/50">
      <div class="flex items-center gap-2">
        <span v-if="title" class="text-sm font-medium">{{ title }}</span>
        <span v-if="language" class="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
          {{ language }}
        </span>
      </div>
      <Button
        v-if="showCopy"
        variant="ghost"
        size="sm"
        class="h-8 w-8 p-0"
        @click="copyCode"
      >
        <Check v-if="copied" class="h-4 w-4 text-green-500" />
        <Copy v-else class="h-4 w-4" />
      </Button>
    </CardHeader>
    <CardContent class="p-0">
      <div
        class="overflow-auto"
        :style="containerStyle"
      >
        <div class="flex">
          <!-- 行号 -->
          <div
            v-if="showLineNumbers"
            class="flex-shrink-0 bg-muted/50 text-muted-foreground text-sm text-right select-none pr-4 py-4"
          >
            <div
              v-for="line in lineNumbers"
              :key="line"
              class="px-2"
              :class="{
                'bg-primary/10': isLineHighlighted(line),
              }"
            >
              {{ line }}
            </div>
          </div>

          <!-- 代码内容 -->
          <div class="flex-1 py-4 px-4">
            <div
              v-for="(line, index) in codeLines"
              :key="index"
              :class="[
                codeClass,
                {
                  'bg-primary/10': isLineHighlighted(index + 1),
                },
              ]"
            >
              {{ line }}
            </div>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
