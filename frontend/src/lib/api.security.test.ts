import { afterEach, describe, expect, it } from 'vitest'
import { accessToken, clearSession, setAccessToken } from './api'

afterEach(() => {
  clearSession()
  localStorage.clear()
})

describe('browser credential storage', () => {
  it('keeps access credentials in memory and never writes tokens to localStorage', () => {
    setAccessToken('short-lived-access-token')

    expect(accessToken()).toBe('short-lived-access-token')
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('removes credentials left by pre-cookie application versions', () => {
    localStorage.setItem('access_token', 'legacy-access-token')
    localStorage.setItem('refresh_token', 'legacy-refresh-token')

    clearSession()

    expect(accessToken()).toBeNull()
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })
})
