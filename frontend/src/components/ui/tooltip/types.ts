export interface TooltipProps {
  content?: string
  placement?: 'top' | 'bottom' | 'left' | 'right'
  disabled?: boolean
  delay?: number
}

export interface TooltipContentProps {
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
}

export interface TooltipProviderProps {
  delayDuration?: number
}

export interface TooltipTriggerProps {
  asChild?: boolean
}
