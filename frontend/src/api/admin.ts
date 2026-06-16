import apiClient from './client'

// --- Types ---

export interface AdminOverview {
  total_users: number
  active_users: number
  total_projects: number
  running_projects: number
  total_papers: number
  total_runs: number
  total_llm_calls: number
  total_cost: number
  total_tokens: number
  providers: Array<{
    id: string
    name: string
    status: string
    total_calls: number
    total_cost: number
  }>
  recent_activities: ActivityLog[]
  daily_usage: DailyUsage[]
}

export interface SourceConfigItem {
  key: string
  label: string
  value: string | null
  is_set: boolean
  key_count: number
  is_enabled: boolean
  value_source: string
  is_secret: boolean
  supports_multiple: boolean
  description: string
  updated_at: string | null
}

export interface ProviderInfo {
  id: string
  kind: string
  display_name: string
  model: string | null
  base_url: string
  api_key_hint: string | null
  is_enabled: boolean
  health_status: string
  priority: number
  rpm_limit: number
  weight: number
  key_strategy: string
  auto_ban: boolean
  test_model: string | null
  input_price_per_m: number
  output_price_per_m: number
  failure_count: number
  last_error: string | null
  last_health_check: string | null
  extra_key_count: number
  created_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProviderCreateRequest {
  kind: string
  display_name: string
  base_url: string
  model?: string
  api_key?: string
  is_enabled?: boolean
  extra_keys?: string[]
  key_strategy?: string
  priority?: number
  rpm_limit?: number
  weight?: number
  auto_ban?: boolean
  test_model?: string
  input_price_per_m?: number
  output_price_per_m?: number
  metadata?: Record<string, unknown>
}

export interface ProviderTestResult {
  provider_id: string
  healthy: boolean
  latency_ms: number | null
  message: string
}

export interface ReloadResult {
  reloaded: number
  message: string
}

export interface ActivityLog {
  id: string
  user_id: string
  action: string
  resource_type: string | null
  created_at: string | null
}

export interface DailyUsage {
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

export interface UsageByProvider {
  provider_name: string
  model_name: string
  call_type: string
  call_count: number
  success_count: number
  error_count: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_cost: number
  avg_latency_ms: number | null
}

export interface LlmCallRecord {
  id: string
  pipeline_run_id?: string
  project_id?: string | null
  project_name?: string | null
  user_id?: string | null
  user_email?: string | null
  node_execution_id?: string | null
  node_name?: string | null
  provider_name: string
  model_name: string
  requested_model?: string | null
  upstream_model?: string | null
  call_type?: string
  status: string
  run_status?: string | null
  error_message?: string | null
  http_status_code?: number | null
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens: number
  cost: number
  input_price_per_m?: number | null
  output_price_per_m?: number | null
  latency_ms: number
  input_preview?: string | null
  output_preview?: string | null
  request_metadata?: Record<string, unknown> | null
  created_at: string
}

export interface AuditLog {
  id: string
  time: string
  user_id: string
  user_email: string
  action: string
  resource_type?: string
  resource_id?: string
  ip_address?: string
  details?: Record<string, unknown>
}

export interface ProjectAdmin {
  id: string
  name: string
  query: string
  status: string
  user_id: string
  user_email: string
  paper_count: number
  created_at: string
}

export interface PipelineConfigItem {
  key: string
  value: string
  label: string
  description: string
  group: string
  type: string
}

// --- API ---

export const adminApi = {
  // Overview
  async getOverview(): Promise<AdminOverview> {
    const { data } = await apiClient.get('/admin/overview')
    return data
  },

  // Providers
  async listProviders(kind?: string): Promise<{ providers: ProviderInfo[]; total: number }> {
    const { data } = await apiClient.get('/admin/providers', { params: kind ? { kind } : {} })
    return data
  },

  async createProvider(payload: ProviderCreateRequest): Promise<ProviderInfo> {
    const { data } = await apiClient.post('/admin/providers', payload)
    return data
  },

  async updateProvider(id: string, payload: Partial<ProviderCreateRequest>): Promise<ProviderInfo> {
    const { data } = await apiClient.patch(`/admin/providers/${id}`, payload)
    return data
  },

  async deleteProvider(id: string): Promise<void> {
    await apiClient.delete(`/admin/providers/${id}`)
  },

  async testProvider(id: string): Promise<ProviderTestResult> {
    const { data } = await apiClient.post(`/admin/providers/${id}/test`)
    return data
  },

  async reloadProviders(): Promise<ReloadResult> {
    const { data } = await apiClient.post('/admin/providers/reload')
    return data
  },

  async toggleProvider(id: string): Promise<{ id: string; is_enabled: boolean; message: string }> {
    const { data } = await apiClient.patch(`/admin/providers/${id}/toggle`)
    return data
  },

  // Users (admin)
  async createUser(payload: { email: string; password: string; full_name?: string; role?: string }): Promise<void> {
    await apiClient.post('/admin/users', payload)
  },

  async deleteUser(id: string): Promise<void> {
    await apiClient.delete(`/admin/users/${id}`)
  },

  async getUserUsage(id: string): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get(`/admin/users/${id}/usage`)
    return data
  },

  // Projects (admin)
  async listAllProjects(params?: { skip?: number; limit?: number; status?: string }): Promise<{ projects: ProjectAdmin[]; total: number }> {
    const { data } = await apiClient.get('/admin/projects', { params })
    return data
  },

  async deleteProject(id: string): Promise<void> {
    await apiClient.delete(`/admin/projects/${id}`)
  },

  // Usage
  async getUsageTrend(days?: number): Promise<DailyUsage[]> {
    const { data } = await apiClient.get('/admin/usage/trend', { params: { days } })
    return data
  },

  async getUsageByProvider(days?: number): Promise<UsageByProvider[]> {
    const { data } = await apiClient.get('/admin/usage/by-provider', { params: { days } })
    return data
  },

  async getRecentCalls(params?: { limit?: number; provider?: string; model?: string }): Promise<LlmCallRecord[]> {
    const { data } = await apiClient.get('/admin/usage/recent-calls', { params })
    return data
  },

  // Audit
  async getAuditLogs(params?: { action?: string; user_id?: string; days?: number; skip?: number; limit?: number }): Promise<{ logs: AuditLog[]; total: number }> {
    const { data } = await apiClient.get('/admin/audit/logs', { params })
    return data
  },

  // Source Config
  async getSourceConfigs(): Promise<SourceConfigItem[]> {
    const { data } = await apiClient.get('/admin/sources')
    return data.configs
  },

  async updateSourceConfig(key: string, payload: { value: string; is_enabled?: boolean }): Promise<SourceConfigItem> {
    const { data } = await apiClient.put(`/admin/sources/${key}`, payload)
    return data
  },

  async appendSourceConfig(key: string, payload: { value: string }): Promise<SourceConfigItem> {
    const { data } = await apiClient.post(`/admin/sources/${key}/append`, payload)
    return data
  },

  async deleteSourceConfig(key: string): Promise<SourceConfigItem> {
    const { data } = await apiClient.delete(`/admin/sources/${key}`)
    return data
  },

  // Pipeline Config
  async getPipelineConfigs(): Promise<PipelineConfigItem[]> {
    const { data } = await apiClient.get('/admin/pipeline-config')
    return data
  },

  async updatePipelineConfig(key: string, value: string): Promise<void> {
    await apiClient.put(`/admin/pipeline-config/${key}`, { value })
  },

  async resetPipelineConfigs(): Promise<void> {
    await apiClient.post('/admin/pipeline-config/reset')
  },
}
