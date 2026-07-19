import { act, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './auth'
import { authApi, SESSION_CLEARED_EVENT } from './api'

vi.mock('./api', () => ({
  SESSION_CLEARED_EVENT: 'academic-cluster:session-cleared',
  authApi: {
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  },
}))

function AuthState() {
  const { isAuthenticated, isAdmin } = useAuth()
  return <span>{isAuthenticated ? (isAdmin ? 'admin' : 'user') : 'anonymous'}</span>
}

describe('AuthProvider', () => {
  it('drops the in-memory identity when refresh-token rotation fails', async () => {
    const user = { id: 'user-1', email: 'admin@example.org', role: 'admin', is_active: true }
    localStorage.setItem('access_token', 'token')
    localStorage.setItem('user', JSON.stringify(user))
    vi.mocked(authApi.me).mockResolvedValue(user)

    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('admin')).toBeInTheDocument())

    act(() => window.dispatchEvent(new Event(SESSION_CLEARED_EVENT)))

    expect(screen.getByText('anonymous')).toBeInTheDocument()
  })
})
