<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Eraser, Undo2, Save, Download } from 'lucide-vue-next'
import type { SignatureProps } from './types'

const props = withDefaults(defineProps<SignatureProps>(), {
  width: 400,
  height: 200,
  lineWidth: 2,
  lineColor: '#000000',
  backgroundColor: '#ffffff',
  penStyle: 'round',
  showClear: true,
  showUndo: true,
  showSave: true,
  showDownload: true,
  disabled: false,
  placeholder: undefined,
  onClear: undefined,
  onUndo: undefined,
  onSave: undefined,
  onDownload: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const isDrawing = ref(false)
const lastX = ref(0)
const lastY = ref(0)
const history = ref<ImageData[]>([])

// 初始化画布
function initCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // 设置画布尺寸
  canvas.width = props.width
  canvas.height = props.height

  // 绘制背景
  ctx.fillStyle = props.backgroundColor
  ctx.fillRect(0, 0, props.width, props.height)

  // 绘制占位符
  if (props.placeholder) {
    ctx.fillStyle = '#9ca3af'
    ctx.font = '14px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(props.placeholder, props.width / 2, props.height / 2)
  }

  // 保存初始状态
  saveState()
}

// 保存当前状态
function saveState() {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  history.value.push(imageData)

  // 限制历史记录数量
  if (history.value.length > 50) {
    history.value.shift()
  }
}

// 开始绘制
function startDrawing(event: MouseEvent | TouchEvent) {
  if (props.disabled) return

  isDrawing.value = true
  const canvas = canvasRef.value
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  const x = (event instanceof MouseEvent ? event.clientX : event.touches[0].clientX) - rect.left
  const y = (event instanceof MouseEvent ? event.clientY : event.touches[0].clientY) - rect.top

  lastX.value = x
  lastY.value = y
}

// 绘制
function draw(event: MouseEvent | TouchEvent) {
  if (!isDrawing.value || props.disabled) return

  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const rect = canvas.getBoundingClientRect()
  const x = (event instanceof MouseEvent ? event.clientX : event.touches[0].clientX) - rect.left
  const y = (event instanceof MouseEvent ? event.clientY : event.touches[0].clientY) - rect.top

  ctx.beginPath()
  ctx.moveTo(lastX.value, lastY.value)
  ctx.lineTo(x, y)
  ctx.strokeStyle = props.lineColor
  ctx.lineWidth = props.lineWidth
  ctx.lineCap = props.penStyle
  ctx.lineJoin = 'round'
  ctx.stroke()

  lastX.value = x
  lastY.value = y
}

// 停止绘制
function stopDrawing() {
  if (!isDrawing.value) return

  isDrawing.value = false
  saveState()
  emitChange()
}

// 清除画布
function clearCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.fillStyle = props.backgroundColor
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  history.value = []
  saveState()
  props.onClear?.()
  emitChange()
}

// 撤销
function undo() {
  if (history.value.length <= 1) return

  history.value.pop()
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const lastState = history.value[history.value.length - 1]
  ctx.putImageData(lastState, 0, 0)

  props.onUndo?.()
  emitChange()
}

// 保存签名
function saveSignature() {
  const canvas = canvasRef.value
  if (!canvas) return

  const data = canvas.toDataURL('image/png')
  props.onSave?.(data)
}

// 下载签名
function downloadSignature() {
  const canvas = canvasRef.value
  if (!canvas) return

  const data = canvas.toDataURL('image/png')
  const link = document.createElement('a')
  link.download = 'signature.png'
  link.href = data
  link.click()

  props.onDownload?.(data)
}

// 触发变化事件
function emitChange() {
  const canvas = canvasRef.value
  if (!canvas) return

  const data = canvas.toDataURL('image/png')
  props.onChange?.(data)
}

// 组件挂载时初始化画布
onMounted(() => {
  initCanvas()

  // 添加全局事件监听
  document.addEventListener('mouseup', stopDrawing)
  document.addEventListener('touchend', stopDrawing)
})

// 组件卸载时清理
onUnmounted(() => {
  document.removeEventListener('mouseup', stopDrawing)
  document.removeEventListener('touchend', stopDrawing)
})
</script>

<template>
  <Card>
    <CardContent class="p-4">
      <div class="flex flex-col gap-4">
        <!-- 画布容器 -->
        <div
          class="relative border border-muted rounded-lg overflow-hidden"
          :style="{ width: `${width}px`, height: `${height}px` }"
        >
          <canvas
            ref="canvasRef"
            class="cursor-crosshair"
            :class="{ 'cursor-not-allowed': disabled }"
            @mousedown="startDrawing"
            @mousemove="draw"
            @mouseup="stopDrawing"
            @mouseleave="stopDrawing"
            @touchstart.prevent="startDrawing"
            @touchmove.prevent="draw"
            @touchend="stopDrawing"
          />
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center gap-2">
          <Button
            v-if="showClear"
            variant="outline"
            size="sm"
            :disabled="disabled"
            @click="clearCanvas"
          >
            <Eraser class="h-4 w-4 mr-2" />
            {{ t('signature.clear') }}
          </Button>
          <Button
            v-if="showUndo"
            variant="outline"
            size="sm"
            :disabled="disabled || history.length <= 1"
            @click="undo"
          >
            <Undo2 class="h-4 w-4 mr-2" />
            {{ t('signature.undo') }}
          </Button>
          <Button
            v-if="showSave"
            variant="default"
            size="sm"
            :disabled="disabled"
            @click="saveSignature"
          >
            <Save class="h-4 w-4 mr-2" />
            {{ t('signature.save') }}
          </Button>
          <Button
            v-if="showDownload"
            variant="outline"
            size="sm"
            :disabled="disabled"
            @click="downloadSignature"
          >
            <Download class="h-4 w-4 mr-2" />
            {{ t('signature.download') }}
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
