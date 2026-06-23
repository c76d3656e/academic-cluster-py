export interface CalendarEvent {
  id: string
  title: string
  start: Date
  end: Date
  allDay?: boolean
  color?: string
  description?: string
  location?: string
  attendees?: { id: string; name: string; avatar?: string }[]
  metadata?: Record<string, unknown>
}

export interface CalendarView {
  type: 'day' | 'week' | 'month'
  date: Date
}

export interface CalendarProps {
  events: CalendarEvent[]
  view?: CalendarView
  onViewChange?: (view: CalendarView) => void
  onEventCreate?: (event: Omit<CalendarEvent, 'id'>) => void
  onEventUpdate?: (event: CalendarEvent) => void
  onEventDelete?: (eventId: string) => void
  onDateClick?: (date: Date) => void
  onEventClick?: (event: CalendarEvent) => void
  editable?: boolean
  selectable?: boolean
}
