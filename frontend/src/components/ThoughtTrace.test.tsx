import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ThoughtTrace } from './ThoughtTrace'

describe('ThoughtTrace', () => {
  it('shows only the six major workflow nodes and their public status', () => {
    render(
      <ThoughtTrace
        activePhase="research"
        progress={[
          {
            node_name: 'supervisor',
            status: 'completed',
            started_at: null,
            finished_at: null,
            elapsed_ms: 120,
            error_message: null,
          },
          {
            node_name: 'research',
            status: 'running',
            started_at: null,
            finished_at: null,
            elapsed_ms: null,
            error_message: null,
          },
        ]}
      />,
    )

    expect(screen.getAllByText(/任务编排|文献检索|证据分析|结构写作|同行评审|成果定稿/)).toHaveLength(6)
    expect(screen.getByText('120 ms')).toBeInTheDocument()
    expect(screen.getByText('正在检索')).toBeInTheDocument()
    expect(screen.queryByText(/工具调用|决策记录|运行摘要/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('执行轨迹').querySelectorAll('.trace-item')).toHaveLength(6)
  })
})
