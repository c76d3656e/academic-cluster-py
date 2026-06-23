export interface ColorPickerProps {
  modelValue?: string
  format?: 'hex' | 'rgb' | 'hsl'
  showAlpha?: boolean
  showPresets?: boolean
  showInput?: boolean
  showEyeDropper?: boolean
  disabled?: boolean
  presets?: string[]
  onUpdate?: (value: string) => void
  onChange?: (value: string) => void
}
