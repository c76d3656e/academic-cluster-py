import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  default: {
    delete: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import apiClient from './client'
import { projectsApi } from './projects'

const mockedClient = vi.mocked(apiClient)

describe('projects pipeline API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not expose removed or unused legacy clients', () => {
    expect(projectsApi).not.toHaveProperty('confirmOutline')
    expect(projectsApi).not.toHaveProperty('getOutline')
    expect(projectsApi).not.toHaveProperty('getVisualization')
  })

  it('normalizes status and phase from an encoded running status', async () => {
    mockedClient.get.mockResolvedValueOnce({
      data: {
        project_id: 'project-1',
        execution_id: 'execution-1',
        status: 'running:agent:peer_review',
      },
    })

    await expect(projectsApi.getProjectStatus('project-1')).resolves.toEqual({
      project_id: 'project-1',
      execution_id: 'execution-1',
      status: 'running',
      current_phase: 'peer_review',
    })
  })

  it('keeps pre-migration projects startable as pending', async () => {
    mockedClient.get.mockResolvedValueOnce({
      data: {
        id: 'project-1',
        name: 'Project',
        query: 'Topic',
        status: 'created',
      },
    })

    await expect(projectsApi.getProject('project-1')).resolves.toMatchObject({
      status: 'pending',
      current_phase: null,
    })
  })

  it.each(['start', 'pause', 'resume'] as const)(
    'uses the canonical pipeline endpoint for %s',
    async (action) => {
      const response = {
        message: `${action} accepted`,
        project_id: 'project-1',
        execution_id: 'execution-1',
      }
      mockedClient.post.mockResolvedValueOnce({ data: response })

      const result = action === 'start'
        ? await projectsApi.startPipeline('project-1')
        : action === 'pause'
          ? await projectsApi.pausePipeline('project-1')
          : await projectsApi.resumePipeline('project-1')

      expect(mockedClient.post).toHaveBeenCalledWith(`/pipeline/project-1/${action}`)
      expect(result).toEqual(response)
    },
  )

  it('rejects removed agent completion aliases from project payloads', async () => {
    mockedClient.get.mockResolvedValueOnce({
      data: {
        id: 'project-1',
        name: 'Project',
        query: 'Topic',
        status: 'agent_completed',
      },
    })

    await expect(projectsApi.getProject('project-1')).rejects.toThrow(
      'Unsupported pipeline status: agent_completed',
    )
  })
})
