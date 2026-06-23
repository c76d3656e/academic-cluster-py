<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Calendar } from '@/components/ui/calendar'
import { CalendarIcon, X } from 'lucide-vue-next'
import { format, isAfter, isBefore, startOfDay, endOfDay, subDays, subMonths, startOfMonth, endOfMonth } from 'date-fns'
import type { DateRangePickerProps, DateRange } from './types'

const props = withDefaults(defineProps<DateRangePickerProps>(), {
  modelValue: () => ({ start: null, end: null }),
  placeholder: 'Select date range',
  format: 'MMM dd, yyyy',
  minDate: undefined,
  maxDate: undefined,
  disabled: false,
  showPresets: true,
  showClear: true,
  presets: undefined,
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const isOpen = ref(false)
const startDate = ref<Date | null>(props.modelValue.start)
const endDate = ref<Date | null>(props.modelValue.end)
const selectingStart = ref(true)

// 计算默认预设
const defaultPresets = computed(() => {
  const today = new Date()
  return [
    {
      label: t('dateRange.today'),
      value: {
        start: startOfDay(today),
        end: endOfDay(today),
      },
    },
    {
      label: t('dateRange.yesterday'),
      value: {
        start: startOfDay(subDays(today, 1)),
        end: endOfDay(subDays(today, 1)),
      },
    },
    {
      label: t('dateRange.last7Days'),
      value: {
        start: startOfDay(subDays(today, 6)),
        end: endOfDay(today),
      },
    },
    {
      label: t('dateRange.last30Days'),
      value: {
        start: startOfDay(subDays(today, 29)),
        end: endOfDay(today),
      },
    },
    {
      label: t('dateRange.thisMonth'),
      value: {
        start: startOfMonth(today),
        end: endOfMonth(today),
      },
    },
    {
      label: t('dateRange.lastMonth'),
      value: {
        start: startOfMonth(subMonths(today, 1)),
        end: endOfMonth(subMonths(today, 1)),
      },
    },
  ]
})

// 计算显示的预设
const displayPresets = computed(() => {
  return props.presets || defaultPresets.value
})

// 计算显示的日期范围
const displayRange = computed(() => {
  if (!startDate.value && !endDate.value) {
    return props.placeholder
  }

  if (startDate.value && !endDate.value) {
    return format(startDate.value, props.format)
  }

  if (startDate.value && endDate.value) {
    return `${format(startDate.value, props.format)} - ${format(endDate.value, props.format)}`
  }

  return props.placeholder
})

// 处理日期选择
function handleDateSelect(date: Date | Date[] | undefined) {
  if (!date || Array.isArray(date)) return

  if (selectingStart.value) {
    startDate.value = date
    selectingStart.value = false
  } else {
    // 确保结束日期不早于开始日期
    if (startDate.value && isBefore(date, startDate.value)) {
      endDate.value = startDate.value
      startDate.value = date
    } else {
      endDate.value = date
    }
    selectingStart.value = true
    emitChange()
  }
}

// 选择预设
function selectPreset(preset: { label: string; value: DateRange }) {
  startDate.value = preset.value.start
  endDate.value = preset.value.end
  emitChange()
  isOpen.value = false
}

// 清除选择
function clearSelection() {
  startDate.value = null
  endDate.value = null
  selectingStart.value = true
  emitChange()
}

// 触发变化事件
function emitChange() {
  const value: DateRange = {
    start: startDate.value,
    end: endDate.value,
  }
  props.onUpdate?.(value)
  props.onChange?.(value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    startDate.value = newValue.start
    endDate.value = newValue.end
  },
  { deep: true }
)
</script>

<template>
  <Popover v-model:open="isOpen">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        class="w-full justify-start text-left font-normal"
        :class="{ 'text-muted-foreground': !startDate && !endDate }"
        :disabled="disabled"
      >
        <CalendarIcon class="mr-2 h-4 w-4" />
        <span class="flex-1 truncate">{{ displayRange }}</span>
        <X
          v-if="showClear && (startDate || endDate)"
          class="h-4 w-4 ml-2 hover:text-destructive"
          @click.stop="clearSelection"
        />
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-auto p-0" align="start">
      <div class="flex">
        <!-- 预设 -->
        <div
          v-if="showPresets"
          class="border-r p-4 space-y-2"
        >
          <div
            v-for="preset in displayPresets"
            :key="preset.label"
            class="cursor-pointer hover:bg-accent rounded-md px-3 py-2 text-sm"
            @click="selectPreset(preset)"
          >
            {{ preset.label }}
          </div>
        </div>

        <!-- 日历 -->
        <div class="p-4">
          <div class="text-sm text-muted-foreground mb-2">
            {{ selectingStart ? t('dateRange.selectStart') : t('dateRange.selectEnd') }}
          </div>
          <Calendar
            :model-value="(selectingStart ? startDate : endDate) ?? undefined"
            :min-date="minDate"
            :max-date="maxDate"
            @update:model-value="handleDateSelect"
          />
        </div>
      </div>
    </PopoverContent>
  </Popover>
</template>
