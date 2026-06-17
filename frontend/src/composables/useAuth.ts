import { useAuthStore } from '@/stores/auth'

/**
 * 薄包装层：将 Pinia store 桥接为 composable 接口，
 * 使所有现有组件代码无需修改导入路径。
 */
export function useAuth() {
  const store = useAuthStore()
  return {
    user: store.user,
    isLoading: store.isLoading,
    isAuthenticated: store.isAuthenticated,
    isAdmin: store.isAdmin,
    login: store.login,
    register: store.register,
    logout: store.logout,
    fetchCurrentUser: store.fetchCurrentUser,
  }
}
