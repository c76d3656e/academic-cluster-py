<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { MarkdownProps } from './types'

const props = withDefaults(defineProps<MarkdownProps>(), {
  sanitize: true,
  breaks: true,
  linkify: true,
  typographer: true,
  highlight: true,
  className: '',
})

// 配置 marked
onMounted(() => {
  marked.setOptions({
    breaks: props.breaks,
    gfm: true,
  })
})

// 计算渲染后的 HTML
const renderedHtml = computed(() => {
  if (!props.content) return ''

  try {
    const rawHtml = marked.parse(props.content) as string

    if (props.sanitize) {
      return DOMPurify.sanitize(rawHtml, {
        ALLOWED_TAGS: [
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'p', 'br', 'hr',
          'strong', 'em', 'del', 's', 'u', 'mark',
          'a', 'img',
          'ul', 'ol', 'li',
          'blockquote',
          'pre', 'code',
          'table', 'thead', 'tbody', 'tr', 'th', 'td',
          'div', 'span',
          'input', 'label',
        ],
        ALLOWED_ATTR: [
          'href', 'src', 'alt', 'title', 'class', 'id',
          'target', 'rel', 'width', 'height',
          'type', 'checked', 'disabled',
          'colspan', 'rowspan',
        ],
      })
    }

    return rawHtml
  } catch (error) {
    console.error('Markdown parsing error:', error)
    return props.content
  }
})

// 计算容器类名
const containerClass = computed(() => {
  const classes = ['prose prose-sm max-w-none', props.className]

  return classes.join(' ')
})
</script>

<template>
  <div
    :class="containerClass"
    v-html="renderedHtml"
  />
</template>

<style scoped>
.prose {
  @apply text-foreground;
}

.prose h1 {
  @apply text-2xl font-bold mb-4 mt-6;
}

.prose h2 {
  @apply text-xl font-bold mb-3 mt-5;
}

.prose h3 {
  @apply text-lg font-bold mb-2 mt-4;
}

.prose h4 {
  @apply text-base font-bold mb-2 mt-3;
}

.prose p {
  @apply mb-4 leading-relaxed;
}

.prose a {
  @apply text-primary hover:underline;
}

.prose strong {
  @apply font-bold;
}

.prose em {
  @apply italic;
}

.prose del {
  @apply line-through;
}

.prose ul {
  @apply list-disc pl-6 mb-4;
}

.prose ol {
  @apply list-decimal pl-6 mb-4;
}

.prose li {
  @apply mb-1;
}

.prose blockquote {
  @apply border-l-4 border-muted pl-4 italic text-muted-foreground mb-4;
}

.prose pre {
  @apply bg-muted p-4 rounded-lg mb-4 overflow-x-auto;
}

.prose code {
  @apply bg-muted px-1.5 py-0.5 rounded text-sm font-mono;
}

.prose pre code {
  @apply bg-transparent p-0;
}

.prose hr {
  @apply border-muted my-6;
}

.prose table {
  @apply w-full border-collapse mb-4;
}

.prose th {
  @apply border border-muted bg-muted px-4 py-2 text-left font-medium;
}

.prose td {
  @apply border border-muted px-4 py-2;
}

.prose img {
  @apply max-w-full h-auto rounded-lg;
}

.prose input[type="checkbox"] {
  @apply mr-2;
}
</style>
