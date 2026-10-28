import type { UIPlan, UIPlanRequest } from '../types/uiPlan'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export async function fetchUIPlan(
  request: UIPlanRequest,
  signal?: AbortSignal
): Promise<UIPlan> {
  const response = await fetch(`${API_BASE_URL}/api/ui-plan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(request),
    signal,
  })

  if (!response.ok) {
    let errorMessage = `Server error (${response.status})`
    try {
      const errJson = await response.json()
      if (errJson?.detail) {
        errorMessage =
          typeof errJson.detail === 'string'
            ? errJson.detail
            : JSON.stringify(errJson.detail)
      }
    } catch {
      // fallback to status code message
    }
    throw new Error(errorMessage)
  }

  const data = (await response.json()) as UIPlan
  return data
}
