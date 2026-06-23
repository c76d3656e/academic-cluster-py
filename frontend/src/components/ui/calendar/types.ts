export interface CalendarProps {
  modelValue?: Date | Date[]
  mode?: 'single' | 'multiple' | 'range'
  disabled?: boolean
}

export interface CalendarDay {
  date: Date
  day: number
  isCurrentMonth: boolean
  isToday: boolean
  isSelected: boolean
}
