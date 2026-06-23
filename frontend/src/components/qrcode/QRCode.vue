<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Download, Copy, Check } from 'lucide-vue-next'
import type { QRCodeProps } from './types'

const props = withDefaults(defineProps<QRCodeProps>(), {
  size: 200,
  level: 'M',
  bgColor: '#ffffff',
  fgColor: '#000000',
  style: 'square',
  logo: undefined,
  logoSize: 40,
  showDownload: true,
  showCopy: true,
  onDownload: undefined,
  onCopy: undefined,
})

const { t } = useI18n()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const copied = ref(false)

// 计算二维码数据（简化版本，实际应用中需要使用二维码生成库）
const qrCodeData = computed(() => {
  // 这里应该使用 qrcode 库来生成二维码
  // 为了简化，这里只是返回一个占位符
  return props.value
})

// 绘制二维码
function drawQRCode() {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // 设置画布尺寸
  canvas.width = props.size
  canvas.height = props.size

  // 绘制背景
  ctx.fillStyle = props.bgColor
  ctx.fillRect(0, 0, props.size, props.size)

  // 绘制二维码（简化版本）
  ctx.fillStyle = props.fgColor
  const cellSize = props.size / 25
  const margin = cellSize * 2

  // 绘制示例二维码图案
  for (let i = 0; i < 25; i++) {
    for (let j = 0; j < 25; j++) {
      if (i < 3 && j < 3 || i < 3 && j > 21 || i > 21 && j < 3) {
        // 定位图案
        ctx.fillRect(
          margin + i * cellSize,
          margin + j * cellSize,
          cellSize,
          cellSize
        )
      } else if ((i + j) % 3 === 0) {
        // 数据图案
        ctx.fillRect(
          margin + i * cellSize,
          margin + j * cellSize,
          cellSize,
          cellSize
        )
      }
    }
  }

  // 绘制 Logo
  if (props.logo) {
    const logoSize = props.logoSize
    const logoX = (props.size - logoSize) / 2
    const logoY = (props.size - logoSize) / 2

    const img = new Image()
    img.onload = () => {
      ctx.save()
      ctx.beginPath()
      ctx.arc(logoX + logoSize / 2, logoY + logoSize / 2, logoSize / 2, 0, Math.PI * 2)
      ctx.clip()
      ctx.drawImage(img, logoX, logoY, logoSize, logoSize)
      ctx.restore()
    }
    img.src = props.logo
  }
}

// 下载二维码
function downloadQRCode() {
  const canvas = canvasRef.value
  if (!canvas) return

  const link = document.createElement('a')
  link.download = 'qrcode.png'
  link.href = canvas.toDataURL('image/png')
  link.click()

  props.onDownload?.()
}

// 复制二维码
async function copyQRCode() {
  const canvas = canvasRef.value
  if (!canvas) return

  try {
    const blob = await new Promise<Blob>((resolve) => {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob)
        }
      }, 'image/png')
    })

    await navigator.clipboard.write([
      new ClipboardItem({
        'image/png': blob,
      }),
    ])

    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)

    props.onCopy?.()
  } catch (error) {
    console.error('Failed to copy QR code:', error)
  }
}

// 监听属性变化
watch(
  () => [props.value, props.size, props.bgColor, props.fgColor],
  () => {
    drawQRCode()
  }
)

// 组件挂载时绘制二维码
onMounted(() => {
  drawQRCode()
})
</script>

<template>
  <Card>
    <CardContent class="p-4">
      <div class="flex flex-col items-center gap-4">
        <!-- 二维码画布 -->
        <canvas
          ref="canvasRef"
          class="border border-muted rounded-lg"
          :style="{
            width: `${size}px`,
            height: `${size}px`,
          }"
        />

        <!-- 操作按钮 -->
        <div class="flex items-center gap-2">
          <Button
            v-if="showDownload"
            variant="outline"
            size="sm"
            @click="downloadQRCode"
          >
            <Download class="h-4 w-4 mr-2" />
            {{ t('qrcode.download') }}
          </Button>
          <Button
            v-if="showCopy"
            variant="outline"
            size="sm"
            @click="copyQRCode"
          >
            <Check v-if="copied" class="h-4 w-4 mr-2 text-green-500" />
            <Copy v-else class="h-4 w-4 mr-2" />
            {{ copied ? t('qrcode.copied') : t('qrcode.copy') }}
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
