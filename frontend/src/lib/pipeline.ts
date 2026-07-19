import { BrainCircuit, FileCheck2, Microscope, PenLine, Search, ShieldCheck, type LucideIcon } from 'lucide-react'
import type { PipelinePhase, PipelineStatus } from './api'

export interface PipelineStage {
  key: PipelinePhase
  label: string
  shortLabel: string
  description: string
  icon: LucideIcon
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { key: 'supervisor', label: '任务编排', shortLabel: '编排', description: '检查状态并决定下一步', icon: BrainCircuit },
  { key: 'research', label: '文献检索', shortLabel: '检索', description: '跨学术源搜索与去重', icon: Search },
  { key: 'analysis', label: '证据分析', shortLabel: '分析', description: '聚类、知识图谱和证据卡', icon: Microscope },
  { key: 'writing', label: '结构写作', shortLabel: '写作', description: '生成大纲与引用约束章节', icon: PenLine },
  { key: 'peer_review', label: '同行评审', shortLabel: '评审', description: '质量审阅和修订决策', icon: ShieldCheck },
  { key: 'finalize', label: '成果定稿', shortLabel: '定稿', description: '汇总摘要、引用与最终稿', icon: FileCheck2 },
]

export function stageFor(phase?: string | null) {
  return PIPELINE_STAGES.find((stage) => stage.key === phase)
}

export function statusLabel(status?: PipelineStatus | string | null) {
  return (
    {
      pending: '等待启动',
      running: '进行中',
      completed: '已完成',
      failed: '失败',
      interrupted: '已暂停',
    }[String(status ?? 'pending')] ?? String(status ?? '未知')
  )
}

export function statusTone(status?: string | null) {
  if (status === 'completed' || status === 'succeeded' || status === 'healthy') return 'success'
  if (status === 'running' || status === 'pending') return 'active'
  if (status === 'failed' || status === 'error' || status === 'unhealthy') return 'danger'
  if (status === 'interrupted' || status === 'cooldown') return 'warning'
  return 'neutral'
}

export function formatNumber(value?: number | null) {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value ?? 0)
}

export function formatCost(value?: number | null) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(
    value ?? 0,
  )
}

export function formatDuration(ms?: number | null) {
  if (!ms && ms !== 0) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function formatDate(value?: string | null, withTime = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: withTime ? '2-digit' : undefined,
    minute: withTime ? '2-digit' : undefined,
  }).format(date)
}
