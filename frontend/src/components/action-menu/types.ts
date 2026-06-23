export interface ActionMenuItem {
  id: string
  label: string
  icon?: string
  shortcut?: string
  disabled?: boolean
  destructive?: boolean
  separator?: boolean
  onClick?: () => void | Promise<void>
}

export interface ActionMenuProps {
  items: ActionMenuItem[]
  trigger?: 'click' | 'hover'
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  disabled?: boolean
  loading?: boolean
}
