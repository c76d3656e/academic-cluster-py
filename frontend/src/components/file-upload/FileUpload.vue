<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Upload, X, File, Loader2 } from 'lucide-vue-next'
import type { FileUploadProps, FileUploadState } from './types'

const props = withDefaults(defineProps<FileUploadProps>(), {
  accept: undefined,
  multiple: false,
  maxSize: 10 * 1024 * 1024, // 10MB
  maxFiles: 5,
  disabled: false,
  loading: false,
  onUpload: undefined,
  onChange: undefined,
  onError: undefined,
  placeholder: 'Drop files here or click to upload',
  description: undefined,
  showPreview: true,
  dragAndDrop: true,
})

const { t } = useI18n()

const state = ref<FileUploadState>({
  files: [],
  isDragging: false,
  isUploading: false,
  error: null,
})

const fileInputRef = ref<HTMLInputElement | null>(null)

// 计算文件列表
const files = computed(() => state.value.files)

// 处理文件选择
function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files) return

  const selectedFiles = Array.from(input.files)
  validateAndAddFiles(selectedFiles)
}

// 处理拖拽
function handleDragEnter(event: DragEvent) {
  event.preventDefault()
  if (props.disabled || !props.dragAndDrop) return
  state.value.isDragging = true
}

function handleDragLeave(event: DragEvent) {
  event.preventDefault()
  state.value.isDragging = false
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  state.value.isDragging = false

  if (props.disabled || !props.dragAndDrop) return

  const droppedFiles = Array.from(event.dataTransfer?.files || [])
  validateAndAddFiles(droppedFiles)
}

// 验证并添加文件
function validateAndAddFiles(newFiles: File[]) {
  state.value.error = null

  // 检查文件数量
  if (state.value.files.length + newFiles.length > props.maxFiles) {
    const error = t('fileUpload.maxFiles', { max: props.maxFiles })
    state.value.error = error
    props.onError?.(error)
    return
  }

  // 验证每个文件
  const validFiles: File[] = []
  for (const file of newFiles) {
    // 检查文件大小
    if (file.size > props.maxSize) {
      const error = t('fileUpload.maxSize', {
        name: file.name,
        size: formatFileSize(props.maxSize),
      })
      state.value.error = error
      props.onError?.(error)
      continue
    }

    // 检查文件类型
    if (props.accept) {
      const acceptedTypes = props.accept.split(',').map((t) => t.trim())
      const isAccepted = acceptedTypes.some((type) => {
        if (type.startsWith('.')) {
          return file.name.toLowerCase().endsWith(type.toLowerCase())
        }
        if (type.endsWith('/*')) {
          const category = type.replace('/*', '')
          return file.type.startsWith(category)
        }
        return file.type === type
      })

      if (!isAccepted) {
        const error = t('fileUpload.invalidType', { name: file.name })
        state.value.error = error
        props.onError?.(error)
        continue
      }
    }

    validFiles.push(file)
  }

  // 添加有效文件
  if (props.multiple) {
    state.value.files = [...state.value.files, ...validFiles]
  } else {
    state.value.files = validFiles.slice(0, 1)
  }

  props.onChange?.(state.value.files)
}

// 移除文件
function removeFile(index: number) {
  state.value.files.splice(index, 1)
  props.onChange?.(state.value.files)
}

// 上传文件
async function handleUpload() {
  if (!props.onUpload || state.value.files.length === 0) return

  state.value.isUploading = true
  try {
    await props.onUpload(state.value.files)
  } finally {
    state.value.isUploading = false
  }
}

// 打开文件选择器
function openFilePicker() {
  if (props.disabled) return
  fileInputRef.value?.click()
}

// 格式化文件大小
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 获取文件图标
function getFileIcon(file: File): string {
  if (file.type.startsWith('image/')) return '🖼️'
  if (file.type.startsWith('video/')) return '🎥'
  if (file.type.startsWith('audio/')) return '🎵'
  if (file.type.includes('pdf')) return '📄'
  if (file.type.includes('word')) return '📝'
  if (file.type.includes('excel') || file.type.includes('spreadsheet')) return '📊'
  return '📁'
}
</script>

<template>
  <div class="space-y-4">
    <!-- 拖拽区域 -->
    <div
      v-if="dragAndDrop"
      class="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors"
      :class="{
        'border-primary bg-primary/5': state.isDragging,
        'border-muted-foreground/25 hover:border-muted-foreground/50': !state.isDragging,
        'opacity-50 cursor-not-allowed': disabled,
      }"
      @click="openFilePicker"
      @dragenter="handleDragEnter"
      @dragleave="handleDragLeave"
      @dragover="handleDragOver"
      @drop="handleDrop"
    >
      <div class="flex flex-col items-center gap-2">
        <Upload class="h-8 w-8 text-muted-foreground" />
        <div class="text-sm font-medium">{{ placeholder }}</div>
        <div v-if="description" class="text-xs text-muted-foreground">
          {{ description }}
        </div>
      </div>
    </div>

    <!-- 上传按钮 -->
    <div v-else>
      <Button
        variant="outline"
        :disabled="disabled"
        @click="openFilePicker"
      >
        <Upload class="h-4 w-4 mr-2" />
        {{ placeholder }}
      </Button>
    </div>

    <!-- 隐藏的文件输入 -->
    <input
      ref="fileInputRef"
      type="file"
      class="hidden"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      @change="handleFileSelect"
    />

    <!-- 错误信息 -->
    <div v-if="state.error" class="text-sm text-destructive">
      {{ state.error }}
    </div>

    <!-- 文件列表 -->
    <div v-if="files.length > 0" class="space-y-2">
      <div
        v-for="(file, index) in files"
        :key="index"
        class="flex items-center gap-3 p-3 border rounded-lg"
      >
        <span class="text-lg">{{ getFileIcon(file) }}</span>
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate">{{ file.name }}</div>
          <div class="text-xs text-muted-foreground">
            {{ formatFileSize(file.size) }}
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          class="h-8 w-8 p-0"
          :disabled="disabled || state.isUploading"
          @click="removeFile(index)"
        >
          <X class="h-4 w-4" />
        </Button>
      </div>

      <!-- 上传按钮 -->
      <Button
        v-if="onUpload"
        class="w-full"
        :disabled="disabled || state.isUploading"
        @click="handleUpload"
      >
        <Loader2 v-if="state.isUploading || loading" class="h-4 w-4 mr-2 animate-spin" />
        {{ t('fileUpload.upload', { count: files.length }) }}
      </Button>
    </div>
  </div>
</template>
