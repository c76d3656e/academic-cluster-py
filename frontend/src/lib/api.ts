import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'

const baseURL = import.meta.env.VITE_API_URL || '/api'

export const api = axios.create({
  baseURL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

type RetryConfig = AxiosRequestConfig & { _retry?: boolean }

export const SESSION_CLEARED_EVENT = 'academic-cluster:session-cleared'

let refreshPromise: Promise<string> | null = null

export function clearSession() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
  window.dispatchEvent(new Event(SESSION_CLEARED_EVENT))
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as RetryConfig | undefined
    const isAuthRequest = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'].some((path) =>
      request?.url?.includes(path),
    )
    if (error.response?.status !== 401 || !request || request._retry || isAuthRequest) {
      return Promise.reject(error)
    }

    request._retry = true
    try {
      const token = await refreshAccessToken()
      request.headers = {
        ...request.headers,
        Authorization: `Bearer ${token}`,
      }
      return api(request)
    } catch (refreshError) {
      return Promise.reject(refreshError)
    }
  },
)

export type UserRole = 'user' | 'admin'

export interface User {
  id: string
  email: string
  full_name?: string | null
  role: UserRole | string
  is_active: boolean
  created_at?: string | null
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type?: string
}

async function rotateRefreshToken(refreshToken: string) {
  try {
    const { data } = await axios.post<TokenResponse>(`${baseURL}/auth/refresh`, {
      refresh_token: refreshToken,
    })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    return data.access_token
  } catch (error) {
    // Another tab may already have completed a rotation while this request failed.
    if (localStorage.getItem('refresh_token') === refreshToken) clearSession()
    throw error
  }
}

async function refreshAcrossTabs(expectedRefreshToken: string) {
  if (!navigator.locks) return rotateRefreshToken(expectedRefreshToken)

  return navigator.locks.request('academic-cluster:token-refresh', async () => {
    const currentRefreshToken = localStorage.getItem('refresh_token')
    const currentAccessToken = localStorage.getItem('access_token')
    if (currentRefreshToken !== expectedRefreshToken) {
      if (currentRefreshToken && currentAccessToken) return currentAccessToken
      throw new Error('The session was cleared while waiting to refresh')
    }
    return rotateRefreshToken(currentRefreshToken)
  })
}

/** Share one refresh-token rotation across Axios, SSE and open browser tabs. */
export function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise

  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) {
    clearSession()
    return Promise.reject(new Error('No refresh token is available'))
  }

  refreshPromise = refreshAcrossTabs(refreshToken).finally(() => {
    refreshPromise = null
  })

  return refreshPromise
}

export interface Project {
  id: string
  name: string
  query: string
  description?: string | null
  status: PipelineStatus
  current_phase?: PipelinePhase | null
  created_at?: string | null
  updated_at?: string | null
  user_id?: string | null
}

export type PipelineStatus = 'pending' | 'running' | 'completed' | 'failed' | 'interrupted'
export type PipelinePhase = 'supervisor' | 'research' | 'analysis' | 'writing' | 'peer_review' | 'finalize'

export interface PipelineAction {
  message: string
  project_id: string
  execution_id: string
}

export interface PipelineStatusResponse {
  project_id: string
  execution_id?: string | null
  status: PipelineStatus
  current_phase: PipelinePhase | null
  current_node?: PipelinePhase | null
  error_message?: string | null
  progress?: { duration_ms?: number; quality_score?: number; status?: string } | null
}

export interface ProgressNode {
  node_name: PipelinePhase | string
  status: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  error_message: string | null
}

export interface ProgressResponse {
  execution_id?: string | null
  nodes: ProgressNode[]
}

export interface SearchSourceSummary {
  source: string
  count: number
  papers: Array<{
    id: string
    title: string
    authors?: unknown
    year?: string | number | null
    journal?: string | null
    doi?: string | null
    url?: string | null
    citation_count?: number
  }>
}

export interface EvidenceCard {
  id: string
  paper_id: string
  claim?: string | null
  evidence_span?: string | null
  method?: string | null
  metric?: string | null
  limitation?: string | null
  confidence?: number | null
  source_api?: string | null
  title?: string | null
  authors?: string | null
  year?: string | number | null
  journal?: string | null
  doi?: string | null
  url?: string | null
}

export interface ReviewResponse {
  project_id: string
  outline: { title?: string; sections?: Array<Record<string, unknown>> } | null
  sections: Array<{
    id?: string
    section_id: string
    content: string
    word_count?: number
    quality_score?: number
  }>
  evidence_cards: EvidenceCard[]
  references?: Array<{
    new_number: number
    original_number: number
    paper_id: string
    title?: string
    authors?: unknown
    venue?: string
    year?: string | number
    doi?: string
    url?: string
  }>
  final_review?: string | null
  abstract?: string | null
  status: PipelineStatus
}

export interface LlmCall {
  id: string
  project_id?: string | null
  project_name?: string | null
  user_email?: string | null
  node_name?: string | null
  provider_name?: string | null
  model_name?: string | null
  requested_model?: string | null
  upstream_model?: string | null
  call_type?: string | null
  status?: string | null
  run_status?: string | null
  error_message?: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
  cost?: number | null
  latency_ms?: number | null
  input_preview?: string | null
  output_preview?: string | null
  request_metadata?: Record<string, unknown> | null
  created_at?: string | null
}

export interface AuditLog {
  id: string
  user_id: string
  user_email?: string | null
  action: string
  resource_type?: string | null
  resource_id?: string | null
  details?: Record<string, unknown> | null
  ip_address?: string | null
  created_at?: string | null
}

export interface UsageTrend {
  date: string
  call_count: number
  total_tokens: number
  total_cost: number
  llm_tokens?: number
  embedding_tokens?: number
  prompt_tokens?: number
  completion_tokens?: number
}

export interface AdminDailyUsage {
  date: string
  calls: number
  tokens: number
  cost: number
}

export interface ConsoleDailyUsage {
  date: string
  token_count: number
  cost: number
}

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
  providers: Array<{ id: string; name: string; status: string; total_calls: number; total_cost: number }>
  recent_activities: Array<{ id: string; user_id: string; action: string; resource_type?: string; created_at?: string }>
  daily_usage: AdminDailyUsage[]
}

export interface ProviderInfo {
  id: string
  kind: 'llm' | 'embedding' | string
  display_name: string
  base_url: string
  model?: string | null
  api_key_hint?: string | null
  is_enabled: boolean
  priority: number
  rpm_limit: number
  health_status: string
  failure_count: number
  last_error?: string | null
  last_health_check?: string | null
  input_price_per_m?: number
  output_price_per_m?: number
}

export interface AdminProject extends Project {
  user_name?: string | null
  user_email?: string | null
  paper_count?: number | null
}

export interface ApiFeatures {
  show_usage?: boolean
  [key: string]: boolean | undefined
}

function normalizeStatus(value: unknown): PipelineStatus {
  const raw = String(value ?? 'pending')
  if (raw.startsWith('running')) return 'running'
  if (raw === 'completed' || raw === 'succeeded') return 'completed'
  if (raw === 'failed') return 'failed'
  if (raw === 'interrupted' || raw === 'cancelled') return 'interrupted'
  return 'pending'
}

function normalizeProject(raw: Record<string, unknown>): Project {
  return {
    ...(raw as unknown as Project),
    status: normalizeStatus(raw.status),
    current_phase: (raw.current_phase ?? null) as PipelinePhase | null,
  }
}

export const authApi = {
  async login(email: string, password: string) {
    const { data } = await api.post<TokenResponse>('/auth/login', { email, password })
    return data
  },
  async register(email: string, password: string, full_name?: string) {
    const { data } = await api.post<User>('/auth/register', { email, password, full_name })
    return data
  },
  async me() {
    const { data } = await api.get<User>('/auth/me')
    return data
  },
  async logout(refresh_token: string) {
    await api.post('/auth/logout', { refresh_token })
  },
  async updateMe(payload: { full_name?: string; password?: string }) {
    const { data } = await api.put<User>('/auth/me', payload)
    return data
  },
  async listUsers(skip = 0, limit = 50) {
    const { data } = await api.get<{ users: User[]; total: number }>('/auth/users', { params: { skip, limit } })
    return data
  },
  async changeRole(userId: string, role: string) {
    await api.put(`/auth/users/${userId}/role`, null, { params: { role } })
  },
  async toggleActive(userId: string, is_active: boolean) {
    await api.put(`/auth/users/${userId}/active`, null, { params: { is_active } })
  },
  async stats() {
    const { data } = await api.get<{
      total_users: number
      total_projects: number
      total_papers: number
      active_users: number
    }>('/auth/stats')
    return data
  },
}

export const projectsApi = {
  async create(payload: { name: string; query: string; description?: string; config?: Record<string, unknown> }) {
    const { data } = await api.post<Record<string, unknown>>('/projects', payload)
    return normalizeProject(data)
  },
  async list(skip = 0, limit = 50) {
    const { data } = await api.get<{ projects: Record<string, unknown>[]; total: number }>('/projects', {
      params: { skip, limit },
    })
    return { total: data.total, projects: data.projects.map(normalizeProject) }
  },
  async get(id: string) {
    const { data } = await api.get<Record<string, unknown>>(`/projects/${id}`)
    return normalizeProject(data)
  },
  async status(id: string) {
    const { data } = await api.get<PipelineStatusResponse>(`/projects/${id}/status`)
    return { ...data, status: normalizeStatus(data.status) }
  },
  async start(id: string) {
    const { data } = await api.post<PipelineAction>(`/pipeline/${id}/start`)
    return data
  },
  async pause(id: string) {
    const { data } = await api.post<PipelineAction>(`/pipeline/${id}/pause`)
    return data
  },
  async resume(id: string) {
    const { data } = await api.post<PipelineAction>(`/pipeline/${id}/resume`)
    return data
  },
  async progress(id: string) {
    const { data } = await api.get<ProgressResponse>(`/projects/${id}/progress`)
    return data
  },
  async review(id: string) {
    const { data } = await api.get<ReviewResponse>(`/projects/${id}/review`)
    return { ...data, status: normalizeStatus(data.status) }
  },
  async sources(id: string) {
    const { data } = await api.get<{ project_id: string; total: number; sources: SearchSourceSummary[] }>(
      `/projects/${id}/sources`,
    )
    return data
  },
  async delete(id: string) {
    await api.delete(`/projects/${id}`)
  },
}

export const consoleApi = {
  async overview() {
    const { data } = await api.get('/console/overview')
    return data as {
      project_count: number
      running_projects: number
      total_papers: number
      total_tokens: number
      total_cost: number
      recent_projects: Array<Pick<Project, 'id' | 'name' | 'status' | 'created_at'>>
      daily_usage: ConsoleDailyUsage[]
    }
  },
  async trend(days = 30) {
    const { data } = await api.get<{ trend?: UsageTrend[] } | UsageTrend[]>('/console/usage/trend', {
      params: { days, granularity: 'day' },
    })
    return Array.isArray(data) ? data : (data.trend ?? [])
  },
  async calls(params: Record<string, string | number | undefined> = {}) {
    const { data } = await api.get<{ calls?: LlmCall[] } | LlmCall[]>('/console/usage/calls', { params })
    return Array.isArray(data) ? data : (data.calls ?? [])
  },
  async profile() {
    const { data } = await api.get('/console/profile')
    return data
  },
  async updateProfile(payload: { full_name?: string }) {
    const { data } = await api.patch('/console/profile', payload)
    return data
  },
  async changePassword(payload: { current_password: string; new_password: string }) {
    await api.post('/console/profile/password', payload)
  },
}

export const adminApi = {
  async overview() {
    const { data } = await api.get<AdminOverview>('/admin/overview')
    return data
  },
  async users(skip = 0, limit = 100) {
    const { data } = await api.get<{ users: User[]; total: number }>('/admin/users', { params: { skip, limit } })
    return data
  },
  async createUser(payload: { email: string; password: string; full_name?: string; role?: string }) {
    const { data } = await api.post<User>('/admin/users', payload)
    return data
  },
  async changeRole(id: string, role: string) {
    const { data } = await api.patch(`/admin/users/${id}/role`, { role })
    return data
  },
  async toggleUser(id: string, is_active: boolean) {
    const { data } = await api.patch(`/admin/users/${id}/active`, { is_active })
    return data
  },
  async providers(kind?: string) {
    const { data } = await api.get<{ providers: ProviderInfo[]; total: number }>('/admin/providers', {
      params: kind ? { kind } : {},
    })
    return data
  },
  async createProvider(payload: {
    kind: string
    display_name: string
    base_url: string
    model?: string
    api_key?: string
    is_enabled?: boolean
    priority?: number
    rpm_limit?: number
  }) {
    const { data } = await api.post<ProviderInfo>('/admin/providers', payload)
    return data
  },
  async deleteProvider(id: string) {
    const { data } = await api.delete<{
      id: string
      kind: string
      display_name: string
      reloaded: number
      message: string
    }>(`/admin/providers/${id}`)
    return data
  },
  async toggleProvider(id: string) {
    const { data } = await api.patch(`/admin/providers/${id}/toggle`)
    return data
  },
  async testProvider(id: string) {
    const { data } = await api.post(`/admin/providers/${id}/test`)
    return data as { healthy: boolean; latency_ms?: number; message: string }
  },
  async reloadProviders() {
    const { data } = await api.post('/admin/providers/reload')
    return data
  },
  async projects(params: Record<string, string | number | undefined> = {}) {
    const { data } = await api.get('/admin/projects', { params })
    return data as { projects: AdminProject[]; total: number }
  },
  async usageTrend(days = 30) {
    const { data } = await api.get<UsageTrend[]>('/admin/usage/trend', { params: { days } })
    return data
  },
  async providerUsage(days = 30) {
    const { data } = await api.get('/admin/usage/by-provider', { params: { days } })
    return data
  },
  async recentCalls(
    limitOrParams:
      | number
      | {
          limit?: number
          skip?: number
          call_type?: string
          status?: string
        } = 50,
  ) {
    const params = typeof limitOrParams === 'number' ? { limit: limitOrParams } : limitOrParams
    const { data } = await api.get<LlmCall[]>('/admin/usage/recent-calls', { params })
    return data
  },
  async audit(params: Record<string, string | number | undefined> = {}) {
    const { data } = await api.get('/admin/audit/logs', { params })
    return data as { logs: AuditLog[]; total: number }
  },
  async sources() {
    const { data } = await api.get('/admin/sources')
    return data.configs as Array<Record<string, unknown>>
  },
  async pipelineConfig() {
    const { data } = await api.get('/admin/pipeline-config')
    return data as Array<Record<string, unknown>>
  },
  async updatePipelineConfig(key: string, value: string) {
    await api.put(`/admin/pipeline-config/${key}`, { value })
  },
}

export async function getFeatures(): Promise<ApiFeatures> {
  try {
    const { data } = await api.get<ApiFeatures>('/features')
    return data
  } catch {
    return { show_usage: false }
  }
}

export function apiErrorMessage(error: unknown, fallback = '请求未完成，请稍后重试') {
  const axiosError = error as AxiosError<{ detail?: string }>
  return axiosError.response?.data?.detail || axiosError.message || fallback
}

export function accessToken() {
  return localStorage.getItem('access_token')
}

export function apiBaseUrl() {
  return baseURL
}
