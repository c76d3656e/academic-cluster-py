import {
  Activity,
  ArrowLeft,
  BookMarked,
  CirclePause,
  Download,
  FileDown,
  FileText,
  Network,
  Play,
  RotateCcw,
  Search,
  Sparkles,
} from 'lucide-react'
import { useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { projectsApi, consoleApi, getFeatures, apiErrorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  formatCost,
  formatDuration,
  formatNumber,
  PIPELINE_STAGES,
  stageFor,
  statusLabel,
  statusTone,
} from '../lib/pipeline'
import { downloadText, safeFilename } from '../lib/utils'
import { SourcePanel } from '../components/SourcePanel'
import { ThoughtTrace } from '../components/ThoughtTrace'
import { AcademicReview } from '../components/AcademicReview'
import {
  Badge,
  Button,
  EmptyState,
  MetricCard,
  SectionHeader,
  Skeleton,
  TabsContent,
  TabsList,
  TabsRoot,
  TabsTrigger,
} from '../components/ui'

function formatPaperAuthors(value: unknown) {
  if (typeof value === 'string') return value.trim()
  if (!Array.isArray(value)) return ''
  return value
    .map((author) => {
      if (typeof author === 'string') return author.trim()
      if (!author || typeof author !== 'object') return ''
      const record = author as Record<string, unknown>
      return String(record.name || record.full_name || '').trim()
    })
    .filter(Boolean)
    .join(', ')
}

export function ProjectPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()
  const projectQuery = useQuery({ queryKey: ['project', id], queryFn: () => projectsApi.get(id), enabled: Boolean(id) })
  const statusQuery = useQuery({
    queryKey: ['project-status', id],
    queryFn: () => projectsApi.status(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 3500 : false),
  })
  const progressQuery = useQuery({
    queryKey: ['project-progress', id],
    queryFn: () => projectsApi.progress(id),
    enabled: Boolean(id),
    refetchInterval: statusQuery.data?.status === 'running' ? 4000 : false,
  })
  const reviewQuery = useQuery({
    queryKey: ['project-review', id],
    queryFn: () => projectsApi.review(id),
    enabled: Boolean(id),
    refetchInterval: statusQuery.data?.status === 'running' ? 10_000 : false,
  })
  const sourcesQuery = useQuery({
    queryKey: ['project-sources', id],
    queryFn: () => projectsApi.sources(id),
    enabled: Boolean(id),
    refetchInterval: statusQuery.data?.status === 'running' ? 8000 : false,
  })
  const featuresQuery = useQuery({ queryKey: ['features'], queryFn: getFeatures, staleTime: 60_000 })
  const callsQuery = useQuery({
    queryKey: ['project-calls', id],
    queryFn: () => consoleApi.calls({ project_id: id, limit: 200 }),
    enabled: Boolean(id) && (featuresQuery.data?.show_usage || isAdmin),
    refetchInterval: statusQuery.data?.status === 'running' ? 5000 : false,
  })

  const project = projectQuery.data
  const status = statusQuery.data?.status || project?.status
  const progress = progressQuery.data?.nodes ?? []
  const review = reviewQuery.data
  const activePhase = statusQuery.data?.current_phase
  const hasFinalReview = Boolean(review?.final_review)
  const article = useMemo(() => {
    if (review?.final_review) return review.final_review
    return (review?.sections ?? [])
      .map((section) => `## ${section.section_id.replace(/[_-]/g, ' ')}\n\n${section.content}`)
      .join('\n\n')
  }, [review?.final_review, review?.sections])
  const sourcePapers = useMemo(() => {
    const apiPapers = (sourcesQuery.data?.sources ?? []).flatMap((source) =>
      source.papers.map((paper) => ({ ...paper, source: source.source })),
    )
    if (apiPapers.length > 0) return apiPapers

    const fallback = new Map<string, (typeof apiPapers)[number]>()
    for (const card of review?.evidence_cards ?? []) {
      const paperId = String(card.paper_id || card.id || '').trim()
      if (!paperId || fallback.has(paperId)) continue
      fallback.set(paperId, {
        id: paperId,
        title: card.title || card.claim || paperId,
        authors: card.authors,
        year: card.year,
        journal: card.journal,
        doi: card.doi,
        url: card.url,
        citation_count: 0,
        source: card.source_api || '证据产物',
      })
    }
    return [...fallback.values()]
  }, [review?.evidence_cards, sourcesQuery.data?.sources])
  const sourceCount =
    sourcesQuery.data?.sources.length || new Set(sourcePapers.map((paper) => paper.source || '证据产物')).size
  const totalWords = (review?.sections ?? []).reduce(
    (total, section) => total + (section.word_count || section.content.length),
    0,
  )

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['project', id] }),
      queryClient.invalidateQueries({ queryKey: ['project-status', id] }),
      queryClient.invalidateQueries({ queryKey: ['project-progress', id] }),
    ])
  }

  async function action(kind: 'start' | 'pause' | 'resume') {
    try {
      await projectsApi[kind](id)
      await refreshAll()
      toast.success(kind === 'pause' ? '任务已暂停' : kind === 'resume' ? '任务已恢复' : '研究任务已启动')
    } catch (error) {
      toast.error(apiErrorMessage(error, '操作未完成'))
    }
  }

  function downloadMarkdown() {
    if (!project) return
    const content = hasFinalReview ? article : `# ${review?.outline?.title || project.query}\n\n${article}`
    downloadText(`${safeFilename(project.name || project.query)}.md`, content, 'text/markdown')
  }

  function downloadBib() {
    if (!project) return
    const content = (review?.references ?? [])
      .map(
        (reference, index) =>
          `@article{ref${reference.new_number || index + 1},\n  title = {${reference.title || ''}},\n  author = {${formatPaperAuthors(reference.authors)}},\n  year = {${reference.year || ''}},\n  journal = {${reference.venue || ''}},\n  doi = {${reference.doi || ''}},\n  url = {${reference.url || ''}}\n}`,
      )
      .join('\n\n')
    downloadText(`${safeFilename(project.name || project.query)}.bib`, content, 'application/x-bibtex')
  }

  if (projectQuery.isLoading)
    return (
      <div className="page-loading">
        <Skeleton className="skeleton-title" />
        <Skeleton className="skeleton-panel" />
      </div>
    )
  if (!project)
    return (
      <EmptyState
        icon={<FileText size={24} />}
        title="没有找到这个项目"
        detail="项目可能已删除，或当前账户没有访问权限。"
        action={
          <Link to="/console/projects">
            <Button variant="soft">返回项目</Button>
          </Link>
        }
      />
    )

  return (
    <div className="project-page">
      <header className="project-header">
        <div className="project-header-leading">
          <Link to="/console/projects" className="back-link">
            <ArrowLeft size={16} />
            项目
          </Link>
          <div className="project-title-block">
            <div className="project-title-row">
              <h1>{project.name}</h1>
              <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
            </div>
            <p>{project.query}</p>
          </div>
        </div>
        <div className="project-actions">
          {status === 'pending' && (
            <Button onClick={() => void action('start')}>
              <Play size={15} />
              启动
            </Button>
          )}
          {status === 'running' && (
            <Button variant="outline" onClick={() => void action('pause')}>
              <CirclePause size={15} />
              暂停
            </Button>
          )}
          {(status === 'failed' || status === 'interrupted') && (
            <Button onClick={() => void action('resume')}>
              <RotateCcw size={15} />
              恢复
            </Button>
          )}
          {article && (
            <>
              <Button variant="outline" onClick={downloadMarkdown}>
                <FileDown size={15} />
                Markdown
              </Button>
              <Button variant="ghost" size="icon" onClick={downloadBib} aria-label="下载 BibTeX" title="下载 BibTeX">
                <Download size={16} />
              </Button>
            </>
          )}
        </div>
      </header>

      {status === 'running' && (
        <div className="project-live-band">
          <span className="live-pulse" />
          <strong>{stageFor(activePhase)?.label || 'Agent 执行中'}</strong>
          <span>{stageFor(activePhase)?.description || '正在读取 checkpoint'}</span>
          <Badge tone="active">
            {progress.filter((node) => node.status === 'completed').length}/{PIPELINE_STAGES.length}
          </Badge>
        </div>
      )}

      <div className="project-metrics">
        <MetricCard
          label="来源论文"
          value={formatNumber(sourcesQuery.data?.total || sourcePapers.length)}
          detail={`${sourceCount} 个数据源`}
          icon={<Search size={17} />}
          tone="sage"
        />
        <MetricCard
          label="证据卡"
          value={formatNumber(review?.evidence_cards.length)}
          detail="已纳入的可追溯证据"
          icon={<BookMarked size={17} />}
          tone="amber"
        />
        <MetricCard
          label="输出规模"
          value={formatNumber(totalWords)}
          detail={`${review?.sections.length || 0} 个章节`}
          icon={<FileText size={17} />}
        />
        <MetricCard
          label="模型调用"
          value={formatNumber(callsQuery.data?.length)}
          detail={formatCost(callsQuery.data?.reduce((sum, call) => sum + (call.cost || 0), 0))}
          icon={<Activity size={17} />}
          tone="coral"
        />
      </div>

      <TabsRoot
        key={article ? 'review-ready' : 'review-pending'}
        defaultValue={article ? 'output' : 'trace'}
        className="project-tabs"
      >
        <TabsList className="project-tabs-list">
          <TabsTrigger value="output">
            <FileText size={15} />
            成果
          </TabsTrigger>
          <TabsTrigger value="trace">
            <Sparkles size={15} />
            执行轨迹
          </TabsTrigger>
          <TabsTrigger value="sources">
            <Network size={15} />
            来源与证据
          </TabsTrigger>
          {(featuresQuery.data?.show_usage || isAdmin) && (
            <TabsTrigger value="usage">
              <Activity size={15} />
              模型调用
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="output">
          {article ? (
            <article className="review-article">
              {!hasFinalReview && <h1>{review?.outline?.title || project.query}</h1>}
              {!hasFinalReview && review?.abstract && (
                <div className="article-abstract">
                  <strong>摘要</strong>
                  <p>{review.abstract}</p>
                </div>
              )}
              <div className="markdown-body">
                <AcademicReview markdown={article} references={review?.references ?? []} />
              </div>
            </article>
          ) : (
            <EmptyState
              icon={<FileText size={24} />}
              title={status === 'running' ? '正在形成研究成果' : '还没有可展示的成果'}
              detail={status === 'running' ? '写作节点完成后，章节和引用会出现在这里。' : '启动或恢复研究流程以继续。'}
            />
          )}
        </TabsContent>

        <TabsContent value="trace">
          <ThoughtTrace progress={progress} activePhase={activePhase} />
        </TabsContent>

        <TabsContent value="sources">
          <div className="sources-page-grid">
            <SourcePanel
              review={review}
              progress={progress}
              activePhase={activePhase}
              sources={sourcesQuery.data?.sources}
            />
            <div className="paper-ledger">
              <SectionHeader eyebrow="PAPER LEDGER" title="论文清单" />
              {sourcesQuery.isLoading ? (
                <Skeleton className="skeleton-panel" />
              ) : sourcePapers.length > 0 ? (
                sourcePapers.slice(0, 40).map((paper) => {
                  const metadata = [
                    formatPaperAuthors(paper.authors),
                    paper.journal,
                    paper.year,
                    paper.citation_count ? `${paper.citation_count} 引用` : '',
                  ].filter(Boolean)
                  return (
                    <div className="paper-row" key={`${paper.source}-${paper.id}`}>
                      <span className="paper-source">{paper.source}</span>
                      <div>
                        <strong>{paper.title}</strong>
                        {metadata.length > 0 && <small>{metadata.join(' · ')}</small>}
                      </div>
                      {paper.url && (
                        <a href={paper.url} target="_blank" rel="noreferrer" aria-label="打开论文">
                          <Download size={14} />
                        </a>
                      )}
                    </div>
                  )
                })
              ) : (
                <EmptyState icon={<Search size={20} />} title="暂无论文来源" />
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="usage">
          <div className="table-panel">
            <SectionHeader eyebrow="MODEL ACTIVITY" title="模型调用" detail="只展示当前账户有权限访问的调用记录" />
            {callsQuery.isLoading ? (
              <Skeleton className="skeleton-panel" />
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>节点</th>
                      <th>Provider / 模型</th>
                      <th>Token</th>
                      <th>耗时</th>
                      <th>成本</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(callsQuery.data ?? []).map((call) => (
                      <tr key={call.id}>
                        <td>
                          <code>{call.node_name || 'unknown'}</code>
                        </td>
                        <td>
                          <strong>{call.provider_name || '—'}</strong>
                          <small>{call.upstream_model || call.model_name || '—'}</small>
                        </td>
                        <td>{formatNumber(call.total_tokens)}</td>
                        <td>{formatDuration(call.latency_ms)}</td>
                        <td>{formatCost(call.cost)}</td>
                        <td>
                          <Badge tone={statusTone(call.status)}>{call.status || 'unknown'}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </TabsContent>
      </TabsRoot>
    </div>
  )
}
