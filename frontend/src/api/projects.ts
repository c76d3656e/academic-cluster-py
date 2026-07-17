import apiClient from './client'
import {
  normalizePipelinePhase,
  normalizePipelineStatus,
  type PipelinePhase,
  type PipelineStatus,
} from '@/lib/pipeline'

export interface Project {
  id: string
  name: string
  query: string
  status: PipelineStatus
  current_phase?: PipelinePhase | null
  description?: string
  created_at?: string
  updated_at?: string
  user_id?: string
}

export interface CreateProjectRequest {
  name: string
  query: string
  description?: string
  config?: Record<string, unknown>
}

export interface ProjectListResponse {
  projects: Project[]
  total: number
}

export interface PipelineStatusResponse {
  project_id: string
  execution_id?: string | null
  status: PipelineStatus
  current_phase: PipelinePhase | null
  error_message?: string | null
}

export interface PipelineActionResponse {
  message: string
  project_id: string
  execution_id: string
}

export interface ProjectProgressNode {
  node_name: string
  status: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  error_message: string | null
}

export interface ProjectProgressResponse {
  execution_id?: string | null
  nodes: ProjectProgressNode[]
}

/** 大纲中的单个章节定义 */
export interface OutlineSection {
  id?: string
  name?: string
  title?: string
  heading?: string
  description?: string
  target_words?: number
  key_clusters?: number[]
  key_entities?: string[]
  subsections?: OutlineSection[]
  [key: string]: unknown
}

/** 大纲数据 */
export interface Outline {
  id: string
  project_id: string
  title?: string
  sections?: OutlineSection[]
  status?: string
  version?: number
  [key: string]: unknown
}

/** 已撰写章节 */
export interface WrittenSection {
  id: string
  outline_id: string
  section_id: string
  content: string
  word_count?: number
  quality_score?: number
  version?: number
  created_at?: string
  [key: string]: unknown
}

/** 证据卡片 */
export interface EvidenceCard {
  id: string
  paper_id: string
  claim?: string
  evidence_span?: string
  method?: string
  metric?: string
  limitation?: string
  confidence?: number
  cluster_id?: string
  [key: string]: unknown
}

/** 综述 API 响应 */
export interface ReviewResponse {
  project_id: string
  outline: Outline | null
  sections: WrittenSection[]
  evidence_cards: EvidenceCard[]
  references?: Array<{
    new_number: number
    original_number: number
    paper_id: string
    title?: string
    authors?: string
    venue?: string
    year?: string
    doi?: string
  }>
  final_review?: string
  abstract?: string
  status: PipelineStatus
}

type RawProject = Omit<Project, 'status' | 'current_phase'> & {
  status: unknown
  current_phase?: unknown
}

function normalizeProject(project: RawProject): Project {
  return {
    ...project,
    status: normalizePipelineStatus(project.status),
    current_phase: normalizePipelinePhase(project.current_phase ?? project.status),
  }
}

export const projectsApi = {
  async createProject(data: CreateProjectRequest): Promise<Project> {
    const response = await apiClient.post('/projects', data)
    return normalizeProject(response.data)
  },

  async listProjects(skip = 0, limit = 20): Promise<ProjectListResponse> {
    const response = await apiClient.get('/projects', { params: { skip, limit } })
    return {
      ...response.data,
      projects: response.data.projects.map(normalizeProject),
    }
  },

  async getProject(projectId: string): Promise<Project> {
    const response = await apiClient.get(`/projects/${projectId}`)
    return normalizeProject(response.data)
  },

  async getProjectStatus(projectId: string): Promise<PipelineStatusResponse> {
    const response = await apiClient.get(`/projects/${projectId}/status`)
    const rawStatus = response.data.status
    return {
      ...response.data,
      status: normalizePipelineStatus(rawStatus),
      current_phase: normalizePipelinePhase(
        response.data.current_phase ?? response.data.current_node ?? rawStatus,
      ),
    }
  },

  async startPipeline(projectId: string): Promise<PipelineActionResponse> {
    const response = await apiClient.post(`/pipeline/${projectId}/start`)
    return response.data
  },

  async pausePipeline(projectId: string): Promise<PipelineActionResponse> {
    const response = await apiClient.post(`/pipeline/${projectId}/pause`)
    return response.data
  },

  async resumePipeline(projectId: string): Promise<PipelineActionResponse> {
    const response = await apiClient.post(`/pipeline/${projectId}/resume`)
    return response.data
  },

  async getReview(projectId: string): Promise<ReviewResponse> {
    const response = await apiClient.get(`/projects/${projectId}/review`)
    return {
      ...response.data,
      status: normalizePipelineStatus(response.data.status),
    }
  },

  async deleteProject(projectId: string): Promise<void> {
    await apiClient.delete(`/projects/${projectId}`)
  },

  async getProjectProgress(projectId: string): Promise<ProjectProgressResponse> {
    const response = await apiClient.get(`/projects/${projectId}/progress`)
    return response.data
  },
}
