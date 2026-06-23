import type { ComputedRef, Ref } from 'vue'

export interface RadioGroupProps {
  modelValue?: string | number
  disabled?: boolean
}

export interface RadioGroupItemProps {
  value: string | number
  disabled?: boolean
}

export interface RadioGroupContext {
  selectedValue: ComputedRef<string | number | undefined>
  disabled: ComputedRef<boolean>
  select: (value: string | number) => void
}
