import { AnimatePresence, motion } from 'motion/react'
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  CircleStop,
  FileSearch,
  Lightbulb,
  LoaderCircle,
  PanelRight,
  Plus,
  Search,
  Sparkles,
  WandSparkles,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { projectsApi, type PipelinePhase, type ProgressNode } from '../lib/api'
import { apiErrorMessage } from '../lib/api'
import { useSSE } from '../lib/useSSE'
import { formatDate, PIPELINE_STAGES, stageFor, statusLabel, statusTone } from '../lib/pipeline'
import { useAuth } from '../lib/auth'
import { ThoughtTrace } from '../components/ThoughtTrace'
import { SourcePanel } from '../components/SourcePanel'
import { Badge, Button, Card, CardContent, Hint, IconButton, ProgressBar, Textarea } from '../components/ui'
import { toast } from 'sonner'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  time: string
  phase?: PipelinePhase
}

const starterPrompts = [
  { icon: Search, title: '梳理一个研究领域', prompt: '梳理生成式 AI 在高等教育评估中的研究进展，找出主要争议与空白。' },
  {
    icon: FileSearch,
    title: '比较方法与证据',
    prompt: '比较联邦学习在医疗数据隐私保护中的主流方法，并给出可复核的证据。',
  },
  {
    icon: Lightbulb,
    title: '寻找研究切口',
    prompt: '分析气候适应型城市规划的关键研究方向，提出三个可执行的研究问题。',
  },
  { icon: BookOpen, title: '生成文献综述', prompt: '围绕多智能体系统的可观测性写一篇结构化文献综述，保留引用脉络。' },
]

function phaseFromEvent(value: unknown): PipelinePhase | null {
  const phase = String(value || '')
  return PIPELINE_STAGES.some((stage) => stage.key === phase) ? (phase as PipelinePhase) : null
}

export function ChatPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null)
  const [activePhase, setActivePhase] = useState<PipelinePhase | null>(null)
  const [liveProgress, setLiveProgress] = useState<ProgressNode[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [showTrace, setShowTrace] = useState(true)
  const terminalNotice = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const statusQuery = useQuery({
    queryKey: ['project-status', currentProjectId],
    queryFn: () => projectsApi.status(currentProjectId!),
    enabled: Boolean(currentProjectId),
    refetchInterval: (query) => (submitting || query.state.data?.status === 'running' ? 4000 : false),
  })
  const progressQuery = useQuery({
    queryKey: ['project-progress', currentProjectId],
    queryFn: () => projectsApi.progress(currentProjectId!),
    enabled: Boolean(currentProjectId),
    refetchInterval: statusQuery.data?.status === 'running' ? 4000 : false,
  })
  const reviewQuery = useQuery({
    queryKey: ['project-review', currentProjectId],
    queryFn: () => projectsApi.review(currentProjectId!),
    enabled: Boolean(currentProjectId) && statusQuery.data?.status === 'completed',
  })
  const sourcesQuery = useQuery({
    queryKey: ['project-sources', currentProjectId],
    queryFn: () => projectsApi.sources(currentProjectId!),
    enabled: Boolean(currentProjectId),
    refetchInterval: statusQuery.data?.status === 'running' ? 8000 : false,
  })

  const status = statusQuery.data?.status
  const progress = progressQuery.data?.nodes ?? liveProgress
  const isRunning = status === 'running' || submitting
  const currentStage = stageFor(activePhase || statusQuery.data?.current_phase)
  const percent = useMemo(() => {
    const completed = progress.filter((node) => node.status === 'completed').length
    return Math.round((completed / PIPELINE_STAGES.length) * 100)
  }, [progress])

  useSSE({
    projectId: currentProjectId,
    enabled: Boolean(currentProjectId) && status === 'running',
    onEvent: (event) => {
      if (event.type === 'progress') {
        const phase = phaseFromEvent(event.data.node ?? event.data.phase)
        if (phase) {
          setActivePhase(phase)
          setMessages((current) => {
            const content = String(event.data.message || `正在执行${stageFor(phase)?.label || phase}`)
            const existing = current.find((message) => message.role === 'system' && message.phase === phase)
            if (existing)
              return current.map((message) =>
                message.id === existing.id
                  ? { ...message, content, time: formatDate(new Date().toISOString(), true) }
                  : message,
              )
            return [
              ...current,
              {
                id: crypto.randomUUID(),
                role: 'system',
                content,
                time: formatDate(new Date().toISOString(), true),
                phase,
              },
            ]
          })
        }
      }
      if (event.type === 'complete' || event.type === 'error') {
        void queryClient.invalidateQueries({ queryKey: ['project-status', currentProjectId] })
        void queryClient.invalidateQueries({ queryKey: ['project-progress', currentProjectId] })
        if (event.type === 'error') toast.error(String(event.data.message || 'Agent 执行失败'))
      }
    },
    onTransportError: () => {
      // Status and progress polling remain the authoritative recovery path.
    },
  })

  useEffect(() => {
    if (progressQuery.data?.nodes) setLiveProgress(progressQuery.data.nodes)
  }, [progressQuery.data?.nodes])

  useEffect(() => {
    const terminal =
      status && ['completed', 'failed', 'interrupted'].includes(status) ? `${currentProjectId}:${status}` : null
    if (!terminal || terminal === terminalNotice.current) return
    terminalNotice.current = terminal
    setSubmitting(false)
    setActivePhase(null)
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: status === 'completed' ? 'assistant' : 'system',
        content:
          status === 'completed'
            ? '研究流程已完成。成果、引用和证据卡已经整理好。'
            : `${statusLabel(status)}：${statusQuery.data?.error_message || '可以在项目详情中查看执行轨迹。'}`,
        time: formatDate(new Date().toISOString(), true),
      },
    ])
  }, [currentProjectId, status, statusQuery.data?.error_message])

  useEffect(() => {
    if (messages.length > 0 && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isRunning])

  async function submitResearch(value = prompt) {
    const query = value.trim()
    if (!query || submitting) return
    setPrompt('')
    setSubmitting(true)
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', content: query, time: formatDate(new Date().toISOString(), true) },
    ])
    terminalNotice.current = null
    try {
      const project = await projectsApi.create({ name: query.slice(0, 80), query })
      setCurrentProjectId(project.id)
      await projectsApi.start(project.id)
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content:
            '我会先拆解问题，再跨多个学术源检索，接着分析证据、组织写作并进行同行评审。你可以在右侧看到每一步的执行轨迹。',
          time: formatDate(new Date().toISOString(), true),
        },
      ])
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project-status', project.id] }),
        queryClient.invalidateQueries({ queryKey: ['project-progress', project.id] }),
        queryClient.invalidateQueries({ queryKey: ['projects', 'shell'] }),
      ])
    } catch (error) {
      setSubmitting(false)
      toast.error(apiErrorMessage(error, '研究任务没有成功启动'))
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'system',
          content: apiErrorMessage(error, '研究任务没有成功启动'),
          time: formatDate(new Date().toISOString(), true),
        },
      ])
    }
  }

  async function pauseResearch() {
    if (!currentProjectId) return
    try {
      await projectsApi.pause(currentProjectId)
      await queryClient.invalidateQueries({ queryKey: ['project-status', currentProjectId] })
      toast.success('任务已暂停，checkpoint 已保存')
    } catch (error) {
      toast.error(apiErrorMessage(error, '暂停失败'))
    }
  }

  return (
    <div className="chat-page">
      <header className="chat-header">
        <div>
          <p className="eyebrow">RESEARCH WORKSPACE</p>
          <h1>{currentProjectId ? '进行中的研究' : '新的研究问题'}</h1>
        </div>
        <div className="chat-header-actions">
          <Badge tone={isRunning ? 'active' : statusTone(status)}>
            {isRunning ? 'Agent 在线' : status ? statusLabel(status) : '准备就绪'}
          </Badge>
          <Hint label="显示或隐藏执行轨迹">
            <IconButton
              label="切换执行轨迹"
              variant={showTrace ? 'soft' : 'ghost'}
              onClick={() => setShowTrace((value) => !value)}
            >
              <PanelRight size={17} />
            </IconButton>
          </Hint>
        </div>
      </header>
      <motion.div
        className={`chat-grid ${showTrace ? 'chat-grid-with-rail' : 'chat-grid-full'}`}
        layout
        transition={{ layout: { duration: 0.24, ease: [0.22, 1, 0.36, 1] } }}
      >
        <motion.section className="chat-main-column" layout>
          {currentProjectId && isRunning && (
            <div className="live-progress-banner">
              <div className="live-progress-copy">
                <span className="live-pulse" />
                <span>{currentStage ? `正在${currentStage.label}` : 'Agent 正在准备下一步'}</span>
                <strong>{percent}%</strong>
              </div>
              <ProgressBar value={Math.max(percent, 4)} />
            </div>
          )}
          <div className="chat-transcript" ref={scrollRef} aria-live="polite">
            {messages.length === 0 ? (
              <motion.div className="chat-empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <div className="empty-research-icon">
                  <WandSparkles size={25} />
                </div>
                <p className="eyebrow">ACADEMIC CLUSTER</p>
                <h2>把一个问题，变成一条可复核的证据链。</h2>
                <p className="chat-empty-detail">
                  描述你想研究的主题。Agent 会负责检索、聚类、写作和审阅，并在每一步留下可追溯记录。
                </p>
                <div className="prompt-grid">
                  {starterPrompts.map(({ icon: Icon, title, prompt: value }) => (
                    <button
                      type="button"
                      key={title}
                      className="prompt-card"
                      onClick={() => void submitResearch(value)}
                    >
                      <span className="prompt-icon">
                        <Icon size={17} />
                      </span>
                      <span>
                        <strong>{title}</strong>
                        <small>{value}</small>
                      </span>
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </div>
              </motion.div>
            ) : (
              <AnimatePresence initial={false}>
                {messages.map((message) => (
                  <motion.div
                    key={message.id}
                    className={`chat-message chat-message-${message.role}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    <div className="message-avatar">
                      {message.role === 'user' ? (
                        (user?.full_name || user?.email || '你').slice(0, 1).toUpperCase()
                      ) : message.role === 'assistant' ? (
                        <Sparkles size={15} />
                      ) : (
                        <LoaderCircle size={15} className={message.phase ? 'spin' : ''} />
                      )}
                    </div>
                    <div className="message-body">
                      <div className="message-meta">
                        <strong>
                          {message.role === 'user'
                            ? '你'
                            : message.role === 'assistant'
                              ? 'Academic Cluster'
                              : stageFor(message.phase)?.label || '执行节点'}
                        </strong>
                        <span>{message.time}</span>
                      </div>
                      <p>{message.content}</p>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
            {submitting && (
              <div className="chat-message chat-message-assistant">
                <div className="message-avatar">
                  <LoaderCircle size={15} className="spin" />
                </div>
                <div className="message-body">
                  <div className="message-meta">
                    <strong>Academic Cluster</strong>
                    <span>刚刚</span>
                  </div>
                  <p className="typing-line">
                    <span />
                    <span />
                    <span />
                  </p>
                </div>
              </div>
            )}
            {reviewQuery.data && status === 'completed' && (
              <Card className="result-teaser">
                <CardContent>
                  <div className="result-teaser-icon">
                    <Check size={17} />
                  </div>
                  <div>
                    <p className="eyebrow">RESEARCH OUTPUT READY</p>
                    <h3>{reviewQuery.data.outline?.title || '研究成果已经整理好'}</h3>
                    <p>
                      {reviewQuery.data.sections.length} 个章节 · {reviewQuery.data.evidence_cards.length} 张证据卡 ·{' '}
                      {(reviewQuery.data.references || []).length} 条引用
                    </p>
                  </div>
                  <Button variant="soft" onClick={() => navigate(`/projects/${currentProjectId}`)}>
                    查看成果 <ChevronRight size={15} />
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>
          <div className="composer-wrap">
            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault()
                void submitResearch()
              }}
            >
              <div className="composer-top">
                <Textarea
                  rows={1}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault()
                      void submitResearch()
                    }
                  }}
                  placeholder="描述一个你想研究的问题…"
                  disabled={isRunning}
                  aria-label="研究问题"
                />
                <Button type="submit" size="icon" disabled={!prompt.trim() || isRunning} aria-label="开始研究">
                  <ArrowUp size={18} />
                </Button>
              </div>
              <div className="composer-bottom">
                <span>
                  <Sparkles size={13} />
                  多智能体研究
                </span>
                <span className="composer-hint">Enter 开始 · Shift + Enter 换行</span>
                {isRunning ? (
                  <Button type="button" variant="danger" size="sm" onClick={() => void pauseResearch()}>
                    <CircleStop size={14} />
                    暂停
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setMessages([])
                      setCurrentProjectId(null)
                      setActivePhase(null)
                      setLiveProgress([])
                    }}
                  >
                    <Plus size={14} />
                    新问题
                  </Button>
                )}
              </div>
            </form>
            <p className="composer-disclaimer">研究结果由模型和外部学术源共同生成，请在发表前核验原始来源。</p>
          </div>
        </motion.section>
        <AnimatePresence initial={false} mode="popLayout">
          {showTrace && (
            <motion.aside
              className="chat-right-rail"
              key="research-rail"
              layout
              initial={{ opacity: 0, x: 18 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 18 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            >
              <ThoughtTrace progress={progress} activePhase={activePhase} compact />
              <div className="rail-divider" />
              <SourcePanel
                review={reviewQuery.data}
                progress={progress}
                activePhase={activePhase}
                sources={sourcesQuery.data?.sources}
                compact
              />
            </motion.aside>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
