export interface KanbanItem {
  id: string
  title: string
  description?: string
  status: string
  priority?: 'low' | 'medium' | 'high' | 'urgent'
  assignee?: {
    id: string
    name: string
    avatar?: string
  }
  dueDate?: Date
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface KanbanColumn {
  id: string
  title: string
  status: string
  color?: string
  limit?: number
}

export interface KanbanProps {
  items: KanbanItem[]
  columns: KanbanColumn[]
  onItemMove?: (itemId: string, fromStatus: string, toStatus: string) => void
  onItemCreate?: (columnId: string, item: Omit<KanbanItem, 'id'>) => void
  onItemUpdate?: (item: KanbanItem) => void
  onItemDelete?: (itemId: string) => void
  onColumnAdd?: (column: Omit<KanbanColumn, 'id'>) => void
  onColumnUpdate?: (column: KanbanColumn) => void
  onColumnDelete?: (columnId: string) => void
  draggable?: boolean
  editable?: boolean
}
