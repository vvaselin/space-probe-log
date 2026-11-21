import type { AdminSession } from '~/types/api'
import type { VoyageClock, VoyageLogDetail, VoyageLogItem, VoyagePosition, VoyageStepResult, VoyageSync } from '~/utils/voyage/types'

export function useApi() {
  const config = useRuntimeConfig()
  const base = config.public.apiBase

  async function request<T>(path: string, options: RequestInit & { csrfToken?: string } = {}): Promise<T> {
    const { csrfToken, ...fetchOptions } = options
    const response = await fetch(`${base}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}), ...(options.headers || {}) },
      ...fetchOptions
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `API error ${response.status}`)
    }
    if (response.status === 204) return undefined as T
    return await response.json() as T
  }

  return {
    getVoyageSync: () => request<VoyageSync>('/api/voyage/sync'),
    getVoyageLogs: () => request<VoyageLogItem[]>('/api/voyage/logs'),
    getVoyageLog: (logNumber: string | number) => request<VoyageLogDetail>(`/api/voyage/logs/${logNumber}`),
    getVoyagePosition: (realAt: string) => request<VoyagePosition>(`/api/voyage/position?real_at=${encodeURIComponent(realAt)}`),
    updateVoyageClock: (payload: { mode?: VoyageClock['mode']; interval_seconds?: number }, csrfToken: string) =>
      request<VoyageClock>('/api/voyage/clock', { method: 'PATCH', body: JSON.stringify(payload), csrfToken }),
    pauseVoyage: (csrfToken: string) => request<VoyageClock>('/api/voyage/clock/pause', { method: 'POST', csrfToken }),
    resumeVoyage: (csrfToken: string) => request<VoyageClock>('/api/voyage/clock/resume', { method: 'POST', csrfToken }),
    stepVoyage: (csrfToken: string) => request<VoyageStepResult>('/api/voyage/step', { method: 'POST', csrfToken }),
    loginAdmin: (payload: { username: string; password: string }) =>
      request<AdminSession>('/api/admin/login', { method: 'POST', body: JSON.stringify(payload) }),
    getAdminSession: () => request<AdminSession>('/api/admin/session'),
    logoutAdmin: (csrfToken: string) => request<void>('/api/admin/logout', { method: 'POST', csrfToken })
  }
}
