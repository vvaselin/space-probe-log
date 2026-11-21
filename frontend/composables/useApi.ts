import type { AdminSession, LogDetail, LogListItem, MapPayload, Probe, ProbeNavigation, ProbeSpecification, PromptSettings, SimulationClock, SimulationSettings, SimulationSettingsUpdate, SimulationStep, SimulationTick, StarSystem } from '~/types/api'
import type { VoyageClock, VoyagePosition, VoyageStepResult, VoyageSync } from '~/utils/voyage/types'

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
    getProbe: () => request<Probe>('/api/probe'),
    getProbeSpecification: () => request<ProbeSpecification>('/api/probe/specification'),
    getProbeNavigation: () => request<ProbeNavigation>('/api/probe/navigation'),
    syncProbeNavigation: (csrfToken: string) => request<ProbeNavigation>('/api/probe/navigation/sync', { method: 'POST', csrfToken }),
    getLogs: () => request<LogListItem[]>('/api/logs'),
    getLog: (id: string | number) => request<LogDetail>(`/api/logs/${id}`),
    getSystems: () => request<StarSystem[]>('/api/world/systems'),
    getMap: () => request<MapPayload>('/api/world/map'),
    getVoyageSync: () => request<VoyageSync>('/api/voyage/sync'),
    getVoyagePosition: (realAt: string) => request<VoyagePosition>(`/api/voyage/position?real_at=${encodeURIComponent(realAt)}`),
    updateVoyageClock: (payload: { mode?: VoyageClock['mode']; interval_seconds?: number }, csrfToken: string) =>
      request<VoyageClock>('/api/voyage/clock', { method: 'PATCH', body: JSON.stringify(payload), csrfToken }),
    pauseVoyage: (csrfToken: string) => request<VoyageClock>('/api/voyage/clock/pause', { method: 'POST', csrfToken }),
    resumeVoyage: (csrfToken: string) => request<VoyageClock>('/api/voyage/clock/resume', { method: 'POST', csrfToken }),
    stepVoyage: (csrfToken: string) => request<VoyageStepResult>('/api/voyage/step', { method: 'POST', csrfToken }),
    getPrompts: () => request<PromptSettings>('/api/settings/prompts'),
    getSimulationSettings: () => request<SimulationSettings>('/api/settings/simulation'),
    saveSimulationSettings: (payload: SimulationSettingsUpdate, csrfToken: string) =>
      request<SimulationSettings>('/api/settings/simulation', { method: 'PATCH', body: JSON.stringify(payload), csrfToken }),
    savePrompts: (payload: Pick<PromptSettings, 'probe_profile' | 'action_policy' | 'log_writer_style'>, csrfToken: string) =>
      request<PromptSettings>('/api/settings/prompts', { method: 'PUT', body: JSON.stringify(payload), csrfToken }),
    getClock: () => request<SimulationClock>('/api/simulation/clock'),
    updateClock: (payload: { time_scale?: number; clock_state?: 'running' | 'paused' }, csrfToken: string) =>
      request<SimulationClock>('/api/simulation/clock', { method: 'PATCH', body: JSON.stringify(payload), csrfToken }),
    resetClock: (csrfToken: string) => request<SimulationClock>('/api/simulation/clock/reset', { method: 'POST', csrfToken }),
    step: (csrfToken: string) => request<SimulationStep>('/api/simulation/step', { method: 'POST', csrfToken }),
    tick: (csrfToken: string) => request<SimulationTick>('/api/simulation/tick', { method: 'POST', csrfToken }),
    reset: (csrfToken: string, worldSeed?: string) => request<Probe>('/api/simulation/reset', { method: 'POST', body: JSON.stringify({ world_seed: worldSeed }), csrfToken }),
    loginAdmin: (payload: { username: string; password: string }) =>
      request<AdminSession>('/api/admin/login', { method: 'POST', body: JSON.stringify(payload) }),
    getAdminSession: () => request<AdminSession>('/api/admin/session'),
    logoutAdmin: (csrfToken: string) => request<void>('/api/admin/logout', { method: 'POST', csrfToken })
  }
}
