export interface DateRange {
  start: Date | null
  end: Date | null
}

export interface DateRangePickerProps {
  modelValue?: DateRange
  placeholder?: string
  format?: string
  minDate?: Date
  maxDate?: Date
  disabled?: boolean
  showPresets?: boolean
  showClear?: boolean
  presets?: { label: string; value: DateRange }[]
  onUpdate?: (value: DateRange) => void
  onChange?: (value: DateRange) => void
}
