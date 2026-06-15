import apiClient from './client'

// --- Types ---

export interface ConsoleOverview {
  project_count: number
  running_projects: number
  total_papers: number
  total_tokens: number
  total_cost: number
  daily_usage: Array<{
    date: string
    token_count: number
    cost: number
  }>
  recent_projects: Array<{
    id: string
    name: string
    status: string
    created_at: string | null
  }>
}

export interface ConsoleUsageTrend {
  date: string
  call_count: number
  total_tokens: number
  total_cost: number
  llm_tokens: number
  embedding_tokens: number
  rerank_tokens: number
  llm_cost: number
  embedding_cost: number
  rerank_cost: number
  prompt_tokens: number
  completion_tokens: number
}

export interface ConsoleLlmCall {
  id: string
  pipeline_run_id: string | null
  provider_name: string
  model_name: string
  call_type: string
  status: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  latency_ms: number
  created_at: string | null
  project_id: string | null
}

// --- API ---

export const consoleApi = {
  async getOverview(): Promise<ConsoleOverview> {
    const { data } = await apiClient.get('/console/overview')
    return data
  },

  async getUsageTrend(days?: number): Promise<ConsoleUsageTrend[]> {
    const { data } = await apiClient.get('/console/usage/trend', { params: { days } })
    return data.trend ?? data
  },

  async getMyCalls(params?: { limit?: number; project_id?: string }): Promise<ConsoleLlmCall[]> {
    const { data } = await apiClient.get('/console/usage/calls', { params })
    return data.calls ?? data
  },

  async getProfile(): Promise<{ email: string; full_name: string; role: string; created_at: string }> {
    const { data } = await apiClient.get('/console/profile')
    return data
  },

  async updateProfile(payload: { full_name?: string }): Promise<void> {
    await apiClient.patch('/console/profile', payload)
  },

  async changePassword(payload: { current_password: string; new_password: string }): Promise<void> {
    await apiClient.post('/console/profile/password', payload)
  },
}
