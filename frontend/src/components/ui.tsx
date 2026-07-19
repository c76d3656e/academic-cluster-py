import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as DropdownPrimitive from '@radix-ui/react-dropdown-menu'
import * as ProgressPrimitive from '@radix-ui/react-progress'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { X } from 'lucide-react'
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ComponentPropsWithoutRef,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from '../lib/utils'

export { DropdownPrimitive as DropdownMenu, TabsPrimitive as Tabs, TooltipPrimitive as Tooltip }

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'solid' | 'soft' | 'ghost' | 'outline' | 'danger'
  size?: 'sm' | 'md' | 'lg' | 'icon'
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'solid', size = 'md', ...props }, ref) => (
    <button ref={ref} className={cn('ui-button', `ui-button-${variant}`, `ui-button-${size}`, className)} {...props} />
  ),
)
Button.displayName = 'Button'

export function IconButton({ label, className, ...props }: ButtonProps & { label: string }) {
  return <Button {...props} size="icon" className={className} aria-label={label} title={label} />
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn('ui-input', className)} {...props} />,
)
Input.displayName = 'Input'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn('ui-textarea', className)} {...props} />,
)
Textarea.displayName = 'Textarea'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('ui-card', className)} {...props} />
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('ui-card-header', className)} {...props} />
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('ui-card-content', className)} {...props} />
}

export function Badge({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: 'neutral' | 'active' | 'success' | 'warning' | 'danger'
  className?: string
  children: ReactNode
}) {
  return <span className={cn('status-badge', `status-${tone}`, className)}>{children}</span>
}

export function Divider({ className }: { className?: string }) {
  return <div className={cn('divider', className)} role="separator" />
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <ProgressPrimitive.Root className={cn('progress-root', className)} value={Math.max(0, Math.min(value, 100))}>
      <ProgressPrimitive.Indicator
        className="progress-indicator"
        style={{ transform: `translateX(-${100 - Math.max(0, Math.min(value, 100))}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}

export function Avatar({ name, size = 'md' }: { name?: string | null; size?: 'sm' | 'md' | 'lg' }) {
  const initials = (name || 'AC')
    .split(/[ @]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
  return (
    <span className={cn('avatar', `avatar-${size}`)} aria-label={name || 'Academic Cluster'}>
      {initials || 'AC'}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} aria-hidden="true" />
}

export function EmptyState({
  icon,
  title,
  detail,
  action,
}: {
  icon?: ReactNode
  title: string
  detail?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  )
}

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label className="field-label" htmlFor={htmlFor}>
      {children}
    </label>
  )
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <TooltipPrimitive.Provider delayDuration={250}>{children}</TooltipPrimitive.Provider>
}

export function Hint({ label, children }: { label: string; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content className="tooltip-content" sideOffset={6}>
          {label}
          <TooltipPrimitive.Arrow className="tooltip-arrow" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

export const TabsRoot = TabsPrimitive.Root
export const TabsList = forwardRef<HTMLDivElement, ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(
  ({ className, ...props }, ref) => <TabsPrimitive.List ref={ref} className={cn('tabs-list', className)} {...props} />,
)
TabsList.displayName = 'TabsList'
export const TabsTrigger = forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Trigger ref={ref} className={cn('tabs-trigger', className)} {...props} />
  ),
)
TabsTrigger.displayName = 'TabsTrigger'
export const TabsContent = forwardRef<HTMLDivElement, ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Content ref={ref} className={cn('tabs-content', className)} {...props} />
  ),
)
TabsContent.displayName = 'TabsContent'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
export function DialogContent({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="dialog-overlay" />
      <DialogPrimitive.Content className={cn('dialog-content', className)} {...props}>
        {children}
        <DialogPrimitive.Close asChild>
          <IconButton label="关闭" className="dialog-close" variant="ghost">
            <X size={16} />
          </IconButton>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
export const DialogTitle = DialogPrimitive.Title
export const DialogDescription = DialogPrimitive.Description

export const DropdownMenuTrigger = DropdownPrimitive.Trigger
export const DropdownMenuContent = DropdownPrimitive.Content
export const DropdownMenuItem = DropdownPrimitive.Item
export const DropdownMenuSeparator = DropdownPrimitive.Separator
export const DropdownMenuLabel = DropdownPrimitive.Label

export function SectionHeader({
  eyebrow,
  title,
  detail,
  action,
}: {
  eyebrow?: string
  title: string
  detail?: string
  action?: ReactNode
}) {
  return (
    <div className="section-header">
      <div>
        {eyebrow && <span className="sr-only">{eyebrow}</span>}
        <h2>{title}</h2>
        {detail && <p className="section-detail">{detail}</p>}
      </div>
      {action}
    </div>
  )
}

export function MetricCard({
  label,
  value,
  detail,
  icon,
  tone = 'neutral',
}: {
  label: string
  value: string | number
  detail?: string
  icon: ReactNode
  tone?: 'neutral' | 'sage' | 'amber' | 'coral'
}) {
  return (
    <Card className={cn('metric-card', `metric-${tone}`)}>
      <CardContent>
        <div className="metric-top">
          <span className="metric-label">{label}</span>
          <span className="metric-icon">{icon}</span>
        </div>
        <div className="metric-value">{value}</div>
        {detail && <div className="metric-detail">{detail}</div>}
      </CardContent>
    </Card>
  )
}
