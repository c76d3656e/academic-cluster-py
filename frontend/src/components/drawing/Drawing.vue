<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Pen,
  Square,
  Circle,
  ArrowRight,
  Type,
  Eraser,
  Undo2,
  Trash2,
  Save,
  Download,
  Minus,
  Plus,
} from 'lucide-vue-next'
import type { DrawingProps, DrawingTool } from './types'

const props = withDefaults(defineProps<DrawingProps>(), {
  width: 800,
  height: 600,
  tools: () => [
    { id: 'pen', name: 'Pen', icon: 'pen', type: 'pen' },
    { id: 'line', name: 'Line', icon: 'minus', type: 'line' },
    { id: 'rect', name: 'Rectangle', icon: 'square', type: 'rect' },
    { id: 'circle', name: 'Circle', icon: 'circle', type: 'circle' },
    { id: 'arrow', name: 'Arrow', icon: 'arrow-right', type: 'arrow' },
    { id: 'text', name: 'Text', icon: 'type', type: 'text' },
    { id: 'eraser', name: 'Eraser', icon: 'eraser', type: 'eraser' },
  ],
  defaultTool: 'pen',
  lineWidth: 2,
  lineColor: '#000000',
  fillColor: 'transparent',
  backgroundColor: '#ffffff',
  showTools: true,
  showColors: true,
  showLineWidth: true,
  showClear: true,
  showUndo: true,
  showSave: true,
  showDownload: true,
  disabled: false,
  onClear: undefined,
  onUndo: undefined,
  onSave: undefined,
  onDownload: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const ctx = ref<CanvasRenderingContext2D | null>(null)
const currentTool = ref(props.defaultTool)
const isDrawing = ref(false)
const startX = ref(0)
const startY = ref(0)
const lastX = ref(0)
const lastY = ref(0)
const history = ref<ImageData[]>([])
const currentColor = ref(props.lineColor)
const currentLineWidth = ref(props.lineWidth)

// 计算容器样式
const containerStyle = computed(() => {
  return {
    width: `${props.width}px`,
    height: `${props.height}px`,
  }
})

// 获取图标组件
function getIconComponent(icon: string) {
  switch (icon) {
    case 'pen':
      return Pen
    case 'minus':
      return Minus
    case 'square':
      return Square
    case 'circle':
      return Circle
    case 'arrow-right':
      return ArrowRight
    case 'type':
      return Type
    case 'eraser':
      return Eraser
    default:
      return Pen
  }
}

// 初始化画布
function initCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return

  ctx.value = canvas.getContext('2d')
  if (!ctx.value) return

  // 设置画布尺寸
  canvas.width = props.width
  canvas.height = props.height

  // 绘制背景
  ctx.value.fillStyle = props.backgroundColor
  ctx.value.fillRect(0, 0, props.width, props.height)

  // 保存初始状态
  saveState()
}

// 保存当前状态
function saveState() {
  const canvas = canvasRef.value
  if (!canvas || !ctx.value) return

  const imageData = ctx.value.getImageData(0, 0, canvas.width, canvas.height)
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

  startX.value = x
  startY.value = y
  lastX.value = x
  lastY.value = y

  if (currentTool.value === 'pen' || currentTool.value === 'eraser') {
    if (!ctx.value) return

    ctx.value.beginPath()
    ctx.value.moveTo(x, y)
  }
}

// 绘制
function draw(event: MouseEvent | TouchEvent) {
  if (!isDrawing.value || props.disabled) return

  const canvas = canvasRef.value
  if (!canvas || !ctx.value) return

  const rect = canvas.getBoundingClientRect()
  const x = (event instanceof MouseEvent ? event.clientX : event.touches[0].clientX) - rect.left
  const y = (event instanceof MouseEvent ? event.clientY : event.touches[0].clientY) - rect.top

  if (currentTool.value === 'pen') {
    ctx.value.lineTo(x, y)
    ctx.value.strokeStyle = currentColor.value
    ctx.value.lineWidth = currentLineWidth.value
    ctx.value.lineCap = 'round'
    ctx.value.lineJoin = 'round'
    ctx.value.stroke()
  } else if (currentTool.value === 'eraser') {
    ctx.value.lineTo(x, y)
    ctx.value.strokeStyle = props.backgroundColor
    ctx.value.lineWidth = currentLineWidth.value * 5
    ctx.value.lineCap = 'round'
    ctx.value.lineJoin = 'round'
    ctx.value.stroke()
  }

  lastX.value = x
  lastY.value = y
}

// 停止绘制
function stopDrawing() {
  if (!isDrawing.value) return

  isDrawing.value = false

  if (currentTool.value === 'line' || currentTool.value === 'rect' || currentTool.value === 'circle' || currentTool.value === 'arrow') {
    drawShape()
  }

  saveState()
  emitChange()
}

// 绘制形状
function drawShape() {
  if (!ctx.value) return

  ctx.value.beginPath()
  ctx.value.strokeStyle = currentColor.value
  ctx.value.lineWidth = currentLineWidth.value
  ctx.value.fillStyle = props.fillColor

  if (currentTool.value === 'line') {
    ctx.value.moveTo(startX.value, startY.value)
    ctx.value.lineTo(lastX.value, lastY.value)
    ctx.value.stroke()
  } else if (currentTool.value === 'rect') {
    const width = lastX.value - startX.value
    const height = lastY.value - startY.value
    ctx.value.strokeRect(startX.value, startY.value, width, height)
    if (props.fillColor !== 'transparent') {
      ctx.value.fillRect(startX.value, startY.value, width, height)
    }
  } else if (currentTool.value === 'circle') {
    const radius = Math.sqrt(
      Math.pow(lastX.value - startX.value, 2) + Math.pow(lastY.value - startY.value, 2)
    )
    ctx.value.arc(startX.value, startY.value, radius, 0, Math.PI * 2)
    ctx.value.stroke()
    if (props.fillColor !== 'transparent') {
      ctx.value.fill()
    }
  } else if (currentTool.value === 'arrow') {
    // 绘制箭头
    const angle = Math.atan2(lastY.value - startY.value, lastX.value - startX.value)
    const headLength = 10

    ctx.value.moveTo(startX.value, startY.value)
    ctx.value.lineTo(lastX.value, lastY.value)
    ctx.value.stroke()

    ctx.value.beginPath()
    ctx.value.moveTo(lastX.value, lastY.value)
    ctx.value.lineTo(
      lastX.value - headLength * Math.cos(angle - Math.PI / 6),
      lastY.value - headLength * Math.sin(angle - Math.PI / 6)
    )
    ctx.value.moveTo(lastX.value, lastY.value)
    ctx.value.lineTo(
      lastX.value - headLength * Math.cos(angle + Math.PI / 6),
      lastY.value - headLength * Math.sin(angle + Math.PI / 6)
    )
    ctx.value.stroke()
  }
}

// 清除画布
function clearCanvas() {
  const canvas = canvasRef.value
  if (!canvas || !ctx.value) return

  ctx.value.fillStyle = props.backgroundColor
  ctx.value.fillRect(0, 0, canvas.width, canvas.height)

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
  if (!canvas || !ctx.value) return

  const lastState = history.value[history.value.length - 1]
  ctx.value.putImageData(lastState, 0, 0)

  props.onUndo?.()
  emitChange()
}

// 保存绘图
function saveDrawing() {
  const canvas = canvasRef.value
  if (!canvas) return

  const data = canvas.toDataURL('image/png')
  props.onSave?.(data)
}

// 下载绘图
function downloadDrawing() {
  const canvas = canvasRef.value
  if (!canvas) return

  const data = canvas.toDataURL('image/png')
  const link = document.createElement('a')
  link.download = 'drawing.png'
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

// 选择工具
function selectTool(toolId: string) {
  currentTool.value = toolId
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
        <!-- 工具栏 -->
        <div v-if="showTools" class="flex items-center gap-2 flex-wrap">
          <!-- 工具选择 -->
          <div class="flex items-center gap-1 bg-muted rounded-lg p-1">
            <Button
              v-for="tool in tools"
              :key="tool.id"
              variant="ghost"
              size="sm"
              class="w-8 h-8 p-0"
              :class="{ 'bg-background shadow-sm': currentTool === tool.id }"
              :disabled="disabled"
              @click="selectTool(tool.id)"
            >
              <component :is="getIconComponent(tool.icon)" class="h-4 w-4" />
            </Button>
          </div>

          <Separator orientation="vertical" class="h-6" />

          <!-- 颜色选择 -->
          <div v-if="showColors" class="flex items-center gap-2">
            <input
              type="color"
              :value="currentColor"
              class="w-8 h-8 rounded cursor-pointer"
              @input="currentColor = ($event.target as HTMLInputElement).value"
            />
            <div class="flex gap-1">
              <div
                v-for="color in ['#000000', '#ef4444', '#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6']"
                :key="color"
                class="w-6 h-6 rounded cursor-pointer border border-muted"
                :style="{ backgroundColor: color }"
                @click="currentColor = color"
              />
            </div>
          </div>

          <Separator v-if="showColors" orientation="vertical" class="h-6" />

          <!-- 线宽选择 -->
          <div v-if="showLineWidth" class="flex items-center gap-2">
            <span class="text-sm text-muted-foreground">{{ t('drawing.lineWidth') }}:</span>
            <input
              type="range"
              :value="currentLineWidth"
              min="1"
              max="20"
              class="w-20"
              @input="currentLineWidth = Number(($event.target as HTMLInputElement).value)"
            />
            <span class="text-sm font-medium w-6">{{ currentLineWidth }}</span>
          </div>
        </div>

        <!-- 画布容器 -->
        <div
          class="relative border border-muted rounded-lg overflow-hidden"
          :style="containerStyle"
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
            <Trash2 class="h-4 w-4 mr-2" />
            {{ t('drawing.clear') }}
          </Button>
          <Button
            v-if="showUndo"
            variant="outline"
            size="sm"
            :disabled="disabled || history.length <= 1"
            @click="undo"
          >
            <Undo2 class="h-4 w-4 mr-2" />
            {{ t('drawing.undo') }}
          </Button>
          <Button
            v-if="showSave"
            variant="default"
            size="sm"
            :disabled="disabled"
            @click="saveDrawing"
          >
            <Save class="h-4 w-4 mr-2" />
            {{ t('drawing.save') }}
          </Button>
          <Button
            v-if="showDownload"
            variant="outline"
            size="sm"
            :disabled="disabled"
            @click="downloadDrawing"
          >
            <Download class="h-4 w-4 mr-2" />
            {{ t('drawing.download') }}
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
