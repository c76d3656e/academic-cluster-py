<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ChevronLeft, ChevronRight, Plus } from 'lucide-vue-next'
import type { CalendarProps, CalendarEvent, CalendarView } from './types'

const props = withDefaults(defineProps<CalendarProps>(), {
  view: () => ({ type: 'month', date: new Date() }),
  onViewChange: undefined,
  onEventCreate: undefined,
  onEventUpdate: undefined,
  onEventDelete: undefined,
  onDateClick: undefined,
  onEventClick: undefined,
  editable: true,
  selectable: true,
})

const { t } = useI18n()

const currentDate = ref(props.view.date)
const currentViewType = ref(props.view.type)

// 获取当前月份的天数
const daysInMonth = computed(() => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()
  return new Date(year, month + 1, 0).getDate()
})

// 获取当前月份的第一天是星期几
const firstDayOfMonth = computed(() => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()
  return new Date(year, month, 1).getDay()
})

// 获取日历网格
const calendarGrid = computed(() => {
  const grid: { date: Date; isCurrentMonth: boolean; events: CalendarEvent[] }[] = []
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()

  // 添加上个月的日期
  const firstDay = firstDayOfMonth.value
  for (let i = firstDay - 1; i >= 0; i--) {
    const date = new Date(year, month, -i)
    grid.push({
      date,
      isCurrentMonth: false,
      events: getEventsForDate(date),
    })
  }

  // 添加当前月的日期
  for (let i = 1; i <= daysInMonth.value; i++) {
    const date = new Date(year, month, i)
    grid.push({
      date,
      isCurrentMonth: true,
      events: getEventsForDate(date),
    })
  }

  // 添加下个月的日期
  const remainingDays = 42 - grid.length
  for (let i = 1; i <= remainingDays; i++) {
    const date = new Date(year, month + 1, i)
    grid.push({
      date,
      isCurrentMonth: false,
      events: getEventsForDate(date),
    })
  }

  return grid
})

// 获取指定日期的事件
function getEventsForDate(date: Date): CalendarEvent[] {
  return props.events.filter((event) => {
    const eventStart = new Date(event.start)
    const eventEnd = new Date(event.end)

    if (event.allDay) {
      return (
        eventStart.toDateString() === date.toDateString() ||
        eventEnd.toDateString() === date.toDateString() ||
        (eventStart < date && eventEnd > date)
      )
    }

    return (
      eventStart.toDateString() === date.toDateString() ||
      eventEnd.toDateString() === date.toDateString()
    )
  })
}

// 格式化日期
function formatDate(date: Date): string {
  return date.getDate().toString()
}

// 格式化时间
function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// 判断是否是今天
function isToday(date: Date): boolean {
  const today = new Date()
  return date.toDateString() === today.toDateString()
}

// 判断是否是周末
function isWeekend(date: Date): boolean {
  const day = date.getDay()
  return day === 0 || day === 6
}

// 切换到上一个月/周/日
function previous() {
  const newDate = new Date(currentDate.value)
  switch (currentViewType.value) {
    case 'month':
      newDate.setMonth(newDate.getMonth() - 1)
      break
    case 'week':
      newDate.setDate(newDate.getDate() - 7)
      break
    case 'day':
      newDate.setDate(newDate.getDate() - 1)
      break
  }
  currentDate.value = newDate
  updateView()
}

// 切换到下一个月/周/日
function next() {
  const newDate = new Date(currentDate.value)
  switch (currentViewType.value) {
    case 'month':
      newDate.setMonth(newDate.getMonth() + 1)
      break
    case 'week':
      newDate.setDate(newDate.getDate() + 7)
      break
    case 'day':
      newDate.setDate(newDate.getDate() + 1)
      break
  }
  currentDate.value = newDate
  updateView()
}

// 切换到今天
function goToToday() {
  currentDate.value = new Date()
  updateView()
}

// 切换视图类型
function setViewType(type: 'day' | 'week' | 'month') {
  currentViewType.value = type
  updateView()
}

// 更新视图
function updateView() {
  props.onViewChange?.({
    type: currentViewType.value,
    date: currentDate.value,
  })
}

// 处理日期点击
function handleDateClick(date: Date) {
  if (!props.selectable) return
  props.onDateClick?.(date)
}

// 处理事件点击
function handleEventClick(event: CalendarEvent) {
  props.onEventClick?.(event)
}

// 处理添加事件
function handleAddEvent() {
  if (!props.editable) return

  props.onEventCreate?.({
    title: t('calendar.newEvent'),
    start: new Date(),
    end: new Date(Date.now() + 60 * 60 * 1000), // 1 hour later
  })
}
</script>

<template>
  <Card class="w-full">
    <CardHeader>
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <div class="flex items-center gap-2">
            <Button variant="outline" size="sm" @click="previous">
              <ChevronLeft class="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" @click="goToToday">
              {{ t('calendar.today') }}
            </Button>
            <Button variant="outline" size="sm" @click="next">
              <ChevronRight class="h-4 w-4" />
            </Button>
          </div>
          <h2 class="text-lg font-semibold">
            {{ currentDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) }}
          </h2>
        </div>
        <div class="flex items-center gap-2">
          <div class="flex items-center gap-1 bg-muted rounded-lg p-1">
            <Button
              v-for="viewType in ['day', 'week', 'month']"
              :key="viewType"
              variant="ghost"
              size="sm"
              :class="{ 'bg-background shadow-sm': currentViewType === viewType }"
              @click="setViewType(viewType as 'day' | 'week' | 'month')"
            >
              {{ t(`calendar.${viewType}`) }}
            </Button>
          </div>
          <Button v-if="editable" size="sm" @click="handleAddEvent">
            <Plus class="h-4 w-4 mr-2" />
            {{ t('calendar.addEvent') }}
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent>
      <!-- 星期标题 -->
      <div class="grid grid-cols-7 gap-1 mb-2">
        <div
          v-for="day in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']"
          :key="day"
          class="text-center text-sm font-medium text-muted-foreground py-2"
        >
          {{ t(`calendar.days.${day}`) }}
        </div>
      </div>

      <!-- 日历网格 -->
      <div class="grid grid-cols-7 gap-1">
        <div
          v-for="(day, index) in calendarGrid"
          :key="index"
          class="min-h-[100px] p-2 border rounded-lg"
          :class="{
            'bg-muted/50': !day.isCurrentMonth,
            'bg-background': day.isCurrentMonth,
            'ring-2 ring-primary': isToday(day.date),
            'text-muted-foreground': isWeekend(day.date),
          }"
          @click="handleDateClick(day.date)"
        >
          <div class="flex items-center justify-between mb-1">
            <span
              class="text-sm font-medium"
              :class="{
                'text-primary': isToday(day.date),
                'text-muted-foreground': !day.isCurrentMonth,
              }"
            >
              {{ formatDate(day.date) }}
            </span>
            <Badge
              v-if="day.events.length > 0"
              variant="secondary"
              class="text-xs"
            >
              {{ day.events.length }}
            </Badge>
          </div>

          <!-- 事件列表 -->
          <div class="space-y-1">
            <div
              v-for="event in day.events.slice(0, 2)"
              :key="event.id"
              class="text-xs p-1 rounded cursor-pointer hover:opacity-80"
              :style="{ backgroundColor: event.color || 'hsl(var(--primary))' }"
              @click.stop="handleEventClick(event)"
            >
              <div class="font-medium text-white truncate">
                {{ event.title }}
              </div>
              <div v-if="!event.allDay" class="text-white/80">
                {{ formatTime(event.start) }}
              </div>
            </div>
            <div
              v-if="day.events.length > 2"
              class="text-xs text-muted-foreground text-center"
            >
              +{{ day.events.length - 2 }} more
            </div>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
