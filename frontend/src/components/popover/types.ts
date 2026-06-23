export interface PopoverProps {
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  modal?: boolean
  disabled?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
}
