import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  default: {
    get: vi.fn(),
  },
}))

import apiClient from './client'
import { adminApi } from './admin'

const mockedClient = vi.mocked(apiClient)

describe('admin audit API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the backend audit contract without invented user or timestamp fields', async () => {
    const payload = {
      logs: [
        {
          id: 'audit-1',
          user_id: 'user-1',
          action: 'project.create',
          resource_type: 'project',
          resource_id: 'project-1',
          details: { name: 'Review' },
          ip_address: '127.0.0.1',
          created_at: '2026-07-17 12:00:00+00:00',
        },
      ],
      total: 1,
    }
    mockedClient.get.mockResolvedValueOnce({ data: payload })

    const result = await adminApi.getAuditLogs({ skip: 0, limit: 50 })

    expect(mockedClient.get).toHaveBeenCalledWith('/admin/audit/logs', {
      params: { skip: 0, limit: 50 },
    })
    expect(result).toEqual(payload)
    expect(result.logs[0]).not.toHaveProperty('time')
    expect(result.logs[0]).not.toHaveProperty('user_email')
  })
})
