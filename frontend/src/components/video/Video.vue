<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Play, Pause, Volume2, VolumeX, Maximize } from 'lucide-vue-next'
import type { VideoProps } from './types'

const props = withDefaults(defineProps<VideoProps>(), {
  poster: undefined,
  width: undefined,
  height: undefined,
  autoplay: false,
  loop: false,
  muted: false,
  controls: true,
  preload: 'metadata',
  objectFit: 'contain',
  rounded: false,
  bordered: false,
  onPlay: undefined,
  onPause: undefined,
  onEnded: undefined,
  onError: undefined,
})

const { t } = useI18n()

const videoRef = ref<HTMLVideoElement | null>(null)
const isPlaying = ref(false)
const isMuted = ref(props.muted)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(1)

// 计算容器样式
const containerStyle = computed(() => {
  const style: Record<string, string> = {}

  if (props.width) {
    style.width = typeof props.width === 'number' ? `${props.width}px` : props.width
  }

  if (props.height) {
    style.height = typeof props.height === 'number' ? `${props.height}px` : props.height
  }

  return style
})

// 计算视频样式
const videoStyle = computed(() => {
  return {
    objectFit: props.objectFit,
  }
})

// 计算容器类名
const containerClass = computed(() => {
  const classes: string[] = ['relative']

  if (props.rounded === true) {
    classes.push('rounded-lg')
  } else if (props.rounded === 'sm') {
    classes.push('rounded-sm')
  } else if (props.rounded === 'md') {
    classes.push('rounded-md')
  } else if (props.rounded === 'lg') {
    classes.push('rounded-lg')
  } else if (props.rounded === 'full') {
    classes.push('rounded-full')
  }

  if (props.bordered) {
    classes.push('border border-muted')
  }

  return classes.join(' ')
})

// 播放视频
function play() {
  videoRef.value?.play()
}

// 暂停视频
function pause() {
  videoRef.value?.pause()
}

// 切换播放状态
function togglePlay() {
  if (isPlaying.value) {
    pause()
  } else {
    play()
  }
}

// 切换静音状态
function toggleMute() {
  isMuted.value = !isMuted.value
  if (videoRef.value) {
    videoRef.value.muted = isMuted.value
  }
}

// 设置音量
function setVolume(value: number) {
  volume.value = value
  if (videoRef.value) {
    videoRef.value.volume = value
  }
}

// 跳转到指定时间
function seekTo(time: number) {
  if (videoRef.value) {
    videoRef.value.currentTime = time
  }
}

// 全屏
function enterFullscreen() {
  videoRef.value?.requestFullscreen()
}

// 处理播放事件
function handlePlay() {
  isPlaying.value = true
  props.onPlay?.()
}

// 处理暂停事件
function handlePause() {
  isPlaying.value = false
  props.onPause?.()
}

// 处理结束事件
function handleEnded() {
  isPlaying.value = false
  props.onEnded?.()
}

// 处理错误事件
function handleError(event: Event) {
  props.onError?.(event)
}

// 处理时间更新
function handleTimeUpdate() {
  if (videoRef.value) {
    currentTime.value = videoRef.value.currentTime
  }
}

// 处理元数据加载
function handleLoadedMetadata() {
  if (videoRef.value) {
    duration.value = videoRef.value.duration
  }
}

// 格式化时间
function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.floor(seconds % 60)
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}
</script>

<template>
  <div
    :class="containerClass"
    :style="containerStyle"
  >
    <!-- 视频元素 -->
    <video
      ref="videoRef"
      :src="src"
      :poster="poster"
      :autoplay="autoplay"
      :loop="loop"
      :muted="isMuted"
      :controls="false"
      :preload="preload"
      :style="videoStyle"
      class="w-full h-full"
      @play="handlePlay"
      @pause="handlePause"
      @ended="handleEnded"
      @error="handleError"
      @timeupdate="handleTimeUpdate"
      @loadedmetadata="handleLoadedMetadata"
    />

    <!-- 自定义控件 -->
    <div
      v-if="controls"
      class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4"
    >
      <!-- 进度条 -->
      <div class="mb-2">
        <input
          type="range"
          :value="currentTime"
          :max="duration"
          min="0"
          step="0.1"
          class="w-full h-1 bg-white/30 rounded-lg appearance-none cursor-pointer"
          @input="seekTo(Number(($event.target as HTMLInputElement).value))"
        />
      </div>

      <!-- 控制按钮 -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            class="text-white hover:bg-white/20"
            @click="togglePlay"
          >
            <Pause v-if="isPlaying" class="h-4 w-4" />
            <Play v-else class="h-4 w-4" />
          </Button>

          <div class="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              class="text-white hover:bg-white/20"
              @click="toggleMute"
            >
              <VolumeX v-if="isMuted" class="h-4 w-4" />
              <Volume2 v-else class="h-4 w-4" />
            </Button>
            <input
              type="range"
              :value="volume"
              min="0"
              max="1"
              step="0.1"
              class="w-20 h-1 bg-white/30 rounded-lg appearance-none cursor-pointer"
              @input="setVolume(Number(($event.target as HTMLInputElement).value))"
            />
          </div>

          <span class="text-white text-sm">
            {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
          </span>
        </div>

        <Button
          variant="ghost"
          size="sm"
          class="text-white hover:bg-white/20"
          @click="enterFullscreen"
        >
          <Maximize class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>
