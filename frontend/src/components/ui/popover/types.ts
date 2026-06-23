export interface PopoverProps {
  open?: boolean
  disabled?: boolean
}

export interface PopoverTriggerProps {
  asChild?: boolean
}

export interface PopoverContentProps {
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  sideOffset?: number
}
