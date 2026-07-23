import { motion } from 'motion/react'
import { Check, CircleAlert, CircleDashed, CirclePause, LoaderCircle } from 'lucide-react'
import type { PipelinePhase, ProgressNode } from '../lib/api'
import { PIPELINE_STAGES, formatDuration, stageFor } from '../lib/pipeline'
import { Badge } from './ui'

interface ThoughtTraceProps {
  progress: ProgressNode[]
  activePhase?: PipelinePhase | null
  compact?: boolean
}

type PhaseStatus = 'completed' | 'failed' | 'interrupted' | 'running' | 'pending'

function phaseStatus(progress: ProgressNode | undefined, active: boolean): PhaseStatus {
  if (progress?.status === 'completed') return 'completed'
  if (progress?.status === 'failed') return 'failed'
  if (progress?.status === 'interrupted') return 'interrupted'
  if (active || progress?.status === 'running') return 'running'
  return 'pending'
}

function statusIcon(status: PhaseStatus) {
  if (status === 'completed') return <Check size={14} />
  if (status === 'failed') return <CircleAlert size={14} />
  if (status === 'interrupted') return <CirclePause size={14} />
  if (status === 'running') return <LoaderCircle size={14} className="spin" />
  return <CircleDashed size={14} />
}

function phaseStatusLabel(status: PhaseStatus) {
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'interrupted') return '已暂停'
  if (status === 'running') return '进行中'
  return '等待'
}

export function ThoughtTrace({ progress, activePhase, compact = false }: ThoughtTraceProps) {
  return (
    <section className={compact ? 'thought-trace thought-trace-compact' : 'thought-trace'} aria-label="执行轨迹">
      <div className="trace-heading">
        <h3>执行轨迹</h3>
        <Badge tone={activePhase ? 'active' : 'neutral'}>
          {activePhase ? `正在${stageFor(activePhase)?.shortLabel || activePhase}` : '六节点流程'}
        </Badge>
      </div>
      <div className="trace-list">
        {PIPELINE_STAGES.map((stage, index) => {
          const node = progress.find((item) => item.node_name === stage.key)
          const status = phaseStatus(node, activePhase === stage.key)
          return (
            <motion.div
              key={stage.key}
              className={`trace-item trace-${status}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.18, delay: index * 0.025 }}
              aria-current={status === 'running' ? 'step' : undefined}
            >
              <div className="trace-line" aria-hidden="true" />
              <div className="trace-row">
                <span className="trace-node-icon">{statusIcon(status)}</span>
                <span className="trace-row-main">
                  <span className="trace-row-title">{stage.label}</span>
                  <span className="trace-row-detail">{node?.error_message || phaseStatusLabel(status)}</span>
                </span>
                {node?.elapsed_ms != null && <span className="trace-duration">{formatDuration(node.elapsed_ms)}</span>}
              </div>
            </motion.div>
          )
        })}
      </div>
    </section>
  )
}
