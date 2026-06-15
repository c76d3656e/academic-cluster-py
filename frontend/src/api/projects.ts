import apiClient from './client'

export interface Project {
  id: string
  name: string
  query: string
  status: string
  description?: string
  created_at?: string
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
  status: string
}

export const projectsApi = {
  async createProject(data: CreateProjectRequest): Promise<Project> {
    const response = await apiClient.post('/projects', data)
    return response.data
  },

  async listProjects(skip = 0, limit = 20): Promise<ProjectListResponse> {
    const response = await apiClient.get('/projects', { params: { skip, limit } })
    return response.data
  },

  async getProject(projectId: string): Promise<Project> {
    const response = await apiClient.get(`/projects/${projectId}`)
    return response.data
  },

  async getProjectStatus(projectId: string): Promise<{ project_id: string; status: string }> {
    const response = await apiClient.get(`/projects/${projectId}/status`)
    return response.data
  },

  async startPipeline(projectId: string): Promise<void> {
    await apiClient.post(`/pipeline/${projectId}/start`)
  },

  async getOutline(projectId: string): Promise<unknown> {
    const response = await apiClient.get(`/projects/${projectId}/outline`)
    return response.data
  },

  async confirmOutline(projectId: string, approved: boolean, editedOutline?: unknown): Promise<void> {
    await apiClient.post(`/projects/${projectId}/outline/confirm`, {
      project_id: projectId,
      approved,
      edited_outline: editedOutline,
    })
  },

  async getReview(projectId: string): Promise<ReviewResponse> {
    const response = await apiClient.get(`/projects/${projectId}/review`)
    return response.data
  },

  async getVisualization(projectId: string): Promise<unknown> {
    const response = await apiClient.get(`/projects/${projectId}/visualization`)
    return response.data
  },
}
