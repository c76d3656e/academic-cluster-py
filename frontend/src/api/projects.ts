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

  async getReview(projectId: string): Promise<{ review: string | null; bibtex: string | null }> {
    const response = await apiClient.get(`/projects/${projectId}/review`)
    return response.data
  },

  async getVisualization(projectId: string): Promise<unknown> {
    const response = await apiClient.get(`/projects/${projectId}/visualization`)
    return response.data
  },
}
