<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ZoomIn, ZoomOut, Maximize, MapPin } from 'lucide-vue-next'
import type { MapProps, MapMarker } from './types'

const props = withDefaults(defineProps<MapProps>(), {
  center: () => ({ latitude: 39.9042, longitude: 116.4074 }), // 默认北京
  zoom: 10,
  markers: () => [],
  height: '400px',
  width: '100%',
  showZoomControls: true,
  showLayerControls: false,
  showScale: true,
  draggable: true,
  scrollZoom: true,
  onMarkerClick: undefined,
  onMapClick: undefined,
  onZoomChange: undefined,
  onCenterChange: undefined,
})

const { t } = useI18n()

const currentZoom = ref(props.zoom)
const currentCenter = ref({ ...props.center })

// 计算容器样式
const containerStyle = computed(() => {
  return {
    height: typeof props.height === 'number' ? `${props.height}px` : props.height,
    width: typeof props.width === 'number' ? `${props.width}px` : props.width,
  }
})

// 计算地图 URL（使用 OpenStreetMap）
const mapUrl = computed(() => {
  const { latitude, longitude } = currentCenter.value
  const zoom = currentZoom.value
  return `https://www.openstreetmap.org/export/embed.html?bbox=${longitude - 0.1},${latitude - 0.1},${longitude + 0.1},${latitude + 0.1}&layer=mapnik&marker=${latitude},${longitude}`
})

// 放大
function zoomIn() {
  if (currentZoom.value < 18) {
    currentZoom.value++
    props.onZoomChange?.(currentZoom.value)
  }
}

// 缩小
function zoomOut() {
  if (currentZoom.value > 1) {
    currentZoom.value--
    props.onZoomChange?.(currentZoom.value)
  }
}

// 全屏
function enterFullscreen() {
  // 这里可以实现全屏功能
  // 为了简化，这里只是触发一个事件
}

// 处理标记点击
function handleMarkerClick(marker: MapMarker) {
  props.onMarkerClick?.(marker)
}

// 监听中心点变化
watch(
  () => props.center,
  (newCenter) => {
    currentCenter.value = { ...newCenter }
  },
  { deep: true }
)

// 监听缩放级别变化
watch(
  () => props.zoom,
  (newZoom) => {
    currentZoom.value = newZoom
  }
)
</script>

<template>
  <Card class="overflow-hidden">
    <CardContent class="p-0">
      <!-- 地图容器 -->
      <div
        class="relative"
        :style="containerStyle"
      >
        <!-- 地图 iframe -->
        <iframe
          :src="mapUrl"
          class="w-full h-full border-0"
          :allowfullscreen="true"
          :draggable="draggable"
        />

        <!-- 标记点 -->
        <div
          v-for="marker in markers"
          :key="marker.id"
          class="absolute transform -translate-x-1/2 -translate-y-full cursor-pointer"
          :style="{
            left: `${((marker.longitude - currentCenter.longitude) / 0.2 + 0.5) * 100}%`,
            top: `${((currentCenter.latitude - marker.latitude) / 0.2 + 0.5) * 100}%`,
          }"
          @click="handleMarkerClick(marker)"
        >
          <div class="flex flex-col items-center">
            <MapPin
              class="h-6 w-6"
              :style="{ color: marker.color || '#ef4444' }"
            />
            <div
              v-if="marker.title"
              class="absolute bottom-full mb-1 px-2 py-1 bg-background rounded shadow-lg text-xs whitespace-nowrap"
            >
              {{ marker.title }}
            </div>
          </div>
        </div>

        <!-- 缩放控件 -->
        <div
          v-if="showZoomControls"
          class="absolute top-4 right-4 flex flex-col gap-2"
        >
          <Button
            variant="outline"
            size="sm"
            class="w-8 h-8 p-0 bg-background/80 backdrop-blur-sm"
            @click="zoomIn"
          >
            <ZoomIn class="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="w-8 h-8 p-0 bg-background/80 backdrop-blur-sm"
            @click="zoomOut"
          >
            <ZoomOut class="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="w-8 h-8 p-0 bg-background/80 backdrop-blur-sm"
            @click="enterFullscreen"
          >
            <Maximize class="h-4 w-4" />
          </Button>
        </div>

        <!-- 比例尺 -->
        <div
          v-if="showScale"
          class="absolute bottom-4 left-4 bg-background/80 backdrop-blur-sm px-2 py-1 rounded text-xs"
        >
          {{ t('map.scale') }}: {{ currentZoom }}
        </div>
      </div>
    </CardContent>
  </Card>
</template>
