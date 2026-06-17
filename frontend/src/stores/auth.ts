import { ref, computed, readonly } from 'vue'
import { defineStore } from 'pinia'
import { authApi, type User } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  // ---- State ----
  const user = ref<User | null>(null)
  const isLoading = ref(false)

  // 初始化：从 localStorage 恢复用户信息
  const storedUser = localStorage.getItem('user')
  if (storedUser) {
    try {
      user.value = JSON.parse(storedUser)
    } catch {
      localStorage.removeItem('user')
    }
  }

  // ---- Getters ----
  const isAuthenticated = computed(() => !!user.value && !!localStorage.getItem('access_token'))
  const isAdmin = computed(() => user.value?.role === 'admin')

  // ---- Actions ----
  async function login(email: string, password: string) {
    isLoading.value = true
    try {
      const tokens = await authApi.login({ email, password })
      localStorage.setItem('access_token', tokens.access_token)
      localStorage.setItem('refresh_token', tokens.refresh_token)

      const currentUser = await authApi.getMe()
      user.value = currentUser
      localStorage.setItem('user', JSON.stringify(currentUser))

      return currentUser
    } finally {
      isLoading.value = false
    }
  }

  async function register(email: string, password: string, fullName?: string) {
    isLoading.value = true
    try {
      await authApi.register({ email, password, full_name: fullName })
      // 注册后自动登录
      return await login(email, password)
    } finally {
      isLoading.value = false
    }
  }

  async function logout() {
    const refreshToken = localStorage.getItem('refresh_token')
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken)
      } catch {
        // 忽略登出 API 错误
      }
    }
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
  }

  async function fetchCurrentUser() {
    try {
      const currentUser = await authApi.getMe()
      user.value = currentUser
      localStorage.setItem('user', JSON.stringify(currentUser))
      return currentUser
    } catch {
      user.value = null
      localStorage.removeItem('user')
      return null
    }
  }

  // ---- Expose (readonly state, mutable only via actions) ----
  return {
    user: readonly(user),
    isLoading: readonly(isLoading),
    isAuthenticated,
    isAdmin,
    login,
    register,
    logout,
    fetchCurrentUser,
  }
})
