import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchUIPlan } from '../services/uiPlanService'
import type { UIPlan } from '../types/uiPlan'

describe('uiPlanService', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches and returns a validated UIPlan from /api/ui-plan', async () => {
    const mockPlan: UIPlan = {
      title: 'DevOps Metrics Plan',
      explanation: 'Uptime summary and incident history chart.',
      components: [
        { type: 'card', title: 'System Status', body: 'All systems operational' },
        { type: 'chart', title: 'Deployments', labels: ['Week 1', 'Week 2'], values: [12, 18] },
      ],
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockPlan,
    } as unknown as Response)

    const result = await fetchUIPlan({ prompt: 'Show devops status' })

    expect(result).toEqual(mockPlan)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ui-plan',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ prompt: 'Show devops status' }),
      })
    )
  })

  it('throws descriptive error on HTTP 422 or 500 response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: 'Proposed UI plan failed schema validation' }),
    } as unknown as Response)

    await expect(fetchUIPlan({ prompt: 'Invalid' })).rejects.toThrow(
      'Proposed UI plan failed schema validation'
    )
  })

  it('handles abort signal cleanly', async () => {
    const controller = new AbortController()

    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => {
      controller.abort()
      return Promise.reject(new DOMException('Aborted', 'AbortError'))
    })

    await expect(
      fetchUIPlan({ prompt: 'Cancel me' }, controller.signal)
    ).rejects.toThrow('Aborted')
  })
})
