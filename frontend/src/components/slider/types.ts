export interface SliderProps {
  modelValue?: number | number[]
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  showValue?: boolean
  showTicks?: boolean
  showTooltip?: boolean
  orientation?: 'horizontal' | 'vertical'
  range?: boolean
  marks?: { value: number; label: string }[]
  formatValue?: (value: number) => string
  onUpdate?: (value: number | number[]) => void
  onChange?: (value: number | number[]) => void
}
