import type { ClassValue } from "clsx"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import type { PipelineStatus } from '@/lib/pipeline'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ─── Shared status helpers ──────────────────────────────────────────────

/** Badge variant for project/task status */
export function getStatusVariant(status: PipelineStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'completed': return 'default'
    case 'running': return 'secondary'
    case 'failed': return 'destructive'
    case 'interrupted': return 'outline'
    case 'pending': return 'outline'
  }
}

// ─── Number / token formatting ──────────────────────────────────────────

/** Format large token counts (e.g. 1_234_567 -> "1.2M") */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

/** Format a cost value as USD with 6 decimal places */
export function formatCost(value: number): string {
  return `$${Number(value || 0).toFixed(6)}`
}

// ─── Time formatting ────────────────────────────────────────────────────

/** Current time as HH:MM:SS (zh-CN locale) */
export function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Human-readable runtime between two ISO timestamps */
export function formatRuntime(start: string, end?: string): string {
  const t1 = new Date(start).getTime()
  const t2 = end ? new Date(end).getTime() : Date.now()
  const total = Math.max(0, Math.floor((t2 - t1) / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

// ─── User helpers ───────────────────────────────────────────────────────

/** First two characters of an email, upper-cased (for avatar fallback) */
export function getInitials(email: string): string {
  return email.slice(0, 2).toUpperCase()
}
