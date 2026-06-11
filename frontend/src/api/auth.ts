import apiClient from './client'

export interface User {
  id: string
  email: string
  full_name?: string
  role: string
  is_active: boolean
  created_at?: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
}

export interface SystemStats {
  total_users: number
  total_projects: number
  total_papers: number
  active_users: number
}

export const authApi = {
  async login(data: LoginRequest): Promise<TokenResponse> {
    const response = await apiClient.post<TokenResponse>('/auth/login', data)
    return response.data
  },

  async register(data: RegisterRequest): Promise<User> {
    const response = await apiClient.post<User>('/auth/register', data)
    return response.data
  },

  async refreshToken(refreshToken: string): Promise<TokenResponse> {
    const response = await apiClient.post<TokenResponse>('/auth/refresh', {
      refresh_token: refreshToken,
    })
    return response.data
  },

  async getMe(): Promise<User> {
    const response = await apiClient.get<User>('/auth/me')
    return response.data
  },

  async updateMe(data: { full_name?: string; password?: string }): Promise<User> {
    const response = await apiClient.put<User>('/auth/me', data)
    return response.data
  },

  async logout(refreshToken: string): Promise<void> {
    await apiClient.post('/auth/logout', { refresh_token: refreshToken })
  },

  async listUsers(skip = 0, limit = 20): Promise<{ users: User[]; total: number }> {
    const response = await apiClient.get('/auth/users', { params: { skip, limit } })
    return response.data
  },

  async changeUserRole(userId: string, role: string): Promise<void> {
    await apiClient.put(`/auth/users/${userId}/role`, null, { params: { role } })
  },

  async toggleUserActive(userId: string, isActive: boolean): Promise<void> {
    await apiClient.put(`/auth/users/${userId}/active`, null, { params: { is_active: isActive } })
  },

  async getSystemStats(): Promise<SystemStats> {
    const response = await apiClient.get('/auth/stats')
    return response.data
  },
}
