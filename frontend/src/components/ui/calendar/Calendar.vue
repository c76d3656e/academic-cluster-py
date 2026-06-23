<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CalendarProps, CalendarDay } from './types'

const props = withDefaults(defineProps<CalendarProps>(), {
  modelValue: undefined,
  mode: 'single',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: Date | Date[] | undefined]
}>()

const currentDate = ref(new Date())
const selectedDate = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const daysInMonth = computed(() => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()
  return new Date(year, month + 1, 0).getDate()
})

const firstDayOfMonth = computed(() => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()
  return new Date(year, month, 1).getDay()
})

const days = computed<CalendarDay[]>(() => {
  const result: CalendarDay[] = []
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()

  // 添加上个月的日期
  const prevMonthDays = firstDayOfMonth.value
  const prevMonth = new Date(year, month, 0)
  for (let i = prevMonthDays - 1; i >= 0; i--) {
    result.push({
      date: new Date(prevMonth.getFullYear(), prevMonth.getMonth(), prevMonth.getDate() - i),
      day: prevMonth.getDate() - i,
      isCurrentMonth: false,
      isToday: false,
      isSelected: false,
    })
  }

  // 添加本月的日期
  const today = new Date()
  for (let i = 1; i <= daysInMonth.value; i++) {
    const date = new Date(year, month, i)
    result.push({
      date,
      day: i,
      isCurrentMonth: true,
      isToday: date.toDateString() === today.toDateString(),
      isSelected: selectedDate.value instanceof Date && date.toDateString() === selectedDate.value.toDateString(),
    })
  }

  // 添加下个月的日期
  const remainingDays = 42 - result.length
  for (let i = 1; i <= remainingDays; i++) {
    result.push({
      date: new Date(year, month + 1, i),
      day: i,
      isCurrentMonth: false,
      isToday: false,
      isSelected: false,
    })
  }

  return result
})

const monthYearLabel = computed(() => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()
  return `${year} 年 ${month + 1} 月`
})

function previousMonth() {
  currentDate.value = new Date(currentDate.value.getFullYear(), currentDate.value.getMonth() - 1, 1)
}

function nextMonth() {
  currentDate.value = new Date(currentDate.value.getFullYear(), currentDate.value.getMonth() + 1, 1)
}

function selectDate(day: CalendarDay) {
  if (props.disabled) return
  selectedDate.value = day.date
}
</script>

<template>
  <div class="p-3">
    <div class="flex items-center justify-between mb-4">
      <button
        class="inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground h-7 w-7"
        @click="previousMonth"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m15 18-6-6 6-6"/>
        </svg>
      </button>
      <div class="text-sm font-medium">
        {{ monthYearLabel }}
      </div>
      <button
        class="inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground h-7 w-7"
        @click="nextMonth"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m9 18 6-6-6-6"/>
        </svg>
      </button>
    </div>
    <div class="grid grid-cols-7 gap-1 mb-2">
      <div
        v-for="day in ['日', '一', '二', '三', '四', '五', '六']"
        :key="day"
        class="text-center text-xs text-muted-foreground"
      >
        {{ day }}
      </div>
    </div>
    <div class="grid grid-cols-7 gap-1">
      <button
        v-for="(day, index) in days"
        :key="index"
        :class="[
          'inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground h-9 w-9',
          {
            'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground': day.isSelected,
            'text-muted-foreground opacity-50': !day.isCurrentMonth,
            'bg-accent text-accent-foreground': day.isToday && !day.isSelected,
            'cursor-not-allowed opacity-50': disabled,
          },
        ]"
        @click="selectDate(day)"
      >
        {{ day.day }}
      </button>
    </div>
  </div>
</template>
