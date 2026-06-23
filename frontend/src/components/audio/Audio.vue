<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Play, Pause, Volume2, VolumeX, SkipBack, SkipForward, Repeat, Shuffle } from 'lucide-vue-next'
import type { AudioProps } from './types'

const props = withDefaults(defineProps<AudioProps>(), {
  title: undefined,
  artist: undefined,
  cover: undefined,
  autoplay: false,
  loop: false,
  muted: false,
  controls: true,
  preload: 'metadata',
  showVisualizer: false,
  onPlay: undefined,
  onPause: undefined,
  onEnded: undefined,
  onError: undefined,
})

const { t } = useI18n()

const audioRef = ref<HTMLAudioElement | null>(null)
const isPlaying = ref(false)
const isMuted = ref(props.muted)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(1)
const isLooping = ref(props.loop)

// 计算进度百分比
const progress = computed(() => {
  if (duration.value === 0) return 0
  return (currentTime.value / duration.value) * 100
})

// 播放音频
function play() {
  audioRef.value?.play()
}

// 暂停音频
function pause() {
  audioRef.value?.pause()
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
  if (audioRef.value) {
    audioRef.value.muted = isMuted.value
  }
}

// 设置音量
function setVolume(value: number) {
  volume.value = value
  if (audioRef.value) {
    audioRef.value.volume = value
  }
}

// 跳转到指定时间
function seekTo(time: number) {
  if (audioRef.value) {
    audioRef.value.currentTime = time
  }
}

// 切换循环状态
function toggleLoop() {
  isLooping.value = !isLooping.value
  if (audioRef.value) {
    audioRef.value.loop = isLooping.value
  }
}

// 跳到上一首
function skipBack() {
  seekTo(0)
}

// 跳到下一首
function skipForward() {
  seekTo(duration.value)
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
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
  }
}

// 处理元数据加载
function handleLoadedMetadata() {
  if (audioRef.value) {
    duration.value = audioRef.value.duration
  }
}

// 格式化时间
function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.floor(seconds % 60)
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

// 组件卸载时清理
onUnmounted(() => {
  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.src = ''
  }
})
</script>

<template>
  <Card>
    <CardContent class="p-4">
      <!-- 音频信息 -->
      <div v-if="title || artist" class="flex items-center gap-4 mb-4">
        <div
          v-if="cover"
          class="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0"
        >
          <img
            :src="cover"
            :alt="title"
            class="w-full h-full object-cover"
          />
        </div>
        <div>
          <div v-if="title" class="font-medium">{{ title }}</div>
          <div v-if="artist" class="text-sm text-muted-foreground">{{ artist }}</div>
        </div>
      </div>

      <!-- 音频元素 -->
      <audio
        ref="audioRef"
        :src="src"
        :autoplay="autoplay"
        :loop="isLooping"
        :muted="isMuted"
        :preload="preload"
        @play="handlePlay"
        @pause="handlePause"
        @ended="handleEnded"
        @error="handleError"
        @timeupdate="handleTimeUpdate"
        @loadedmetadata="handleLoadedMetadata"
      />

      <!-- 进度条 -->
      <div class="mb-4">
        <input
          type="range"
          :value="currentTime"
          :max="duration"
          min="0"
          step="0.1"
          class="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer"
          @input="seekTo(Number(($event.target as HTMLInputElement).value))"
        />
        <div class="flex justify-between text-xs text-muted-foreground mt-1">
          <span>{{ formatTime(currentTime) }}</span>
          <span>{{ formatTime(duration) }}</span>
        </div>
      </div>

      <!-- 控制按钮 -->
      <div v-if="controls" class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            @click="toggleLoop"
          >
            <Repeat
              class="h-4 w-4"
              :class="{ 'text-primary': isLooping }"
            />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            @click="skipBack"
          >
            <SkipBack class="h-4 w-4" />
          </Button>
          <Button
            variant="default"
            size="sm"
            class="w-10 h-10 rounded-full"
            @click="togglePlay"
          >
            <Pause v-if="isPlaying" class="h-4 w-4" />
            <Play v-else class="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            @click="skipForward"
          >
            <SkipForward class="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            @click="toggleMute"
          >
            <VolumeX v-if="isMuted" class="h-4 w-4" />
            <Volume2 v-else class="h-4 w-4" />
          </Button>
        </div>

        <!-- 音量控制 -->
        <div class="flex items-center gap-2">
          <input
            type="range"
            :value="volume"
            min="0"
            max="1"
            step="0.1"
            class="w-20 h-1 bg-muted rounded-lg appearance-none cursor-pointer"
            @input="setVolume(Number(($event.target as HTMLInputElement).value))"
          />
        </div>
      </div>
    </CardContent>
  </Card>
</template>
