export interface CommandMenuItem {
  id: string
  label: string
  icon?: string
  shortcut?: string
  disabled?: boolean
  action?: () => void | Promise<void>
  children?: CommandMenuItem[]
}

export interface CommandMenuGroup {
  id: string
  label: string
  items: CommandMenuItem[]
}

export interface CommandMenuProps {
  groups: CommandMenuGroup[]
  placeholder?: string
  emptyMessage?: string
  onSelect?: (item: CommandMenuItem) => void
  onSearch?: (query: string) => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
}
