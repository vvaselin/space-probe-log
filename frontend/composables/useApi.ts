import type { LogDetail, LogListItem, MapPayload, Probe, ProbeNavigation, ProbeSpecification, PromptSettings, SimulationClock, SimulationSettings, SimulationSettingsUpdate, SimulationStep, SimulationTick, StarSystem } from '~/types/api'

export function useApi() {
  const config = useRuntimeConfig()
  const base = config.public.apiBase

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${base}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `API error ${response.status}`)
    }
    return await response.json() as T
  }

  return {
    getProbe: () => request<Probe>('/api/probe'),
    getProbeSpecification: () => request<ProbeSpecification>('/api/probe/specification'),
    getProbeNavigation: () => request<ProbeNavigation>('/api/probe/navigation'),
    syncProbeNavigation: () => request<ProbeNavigation>('/api/probe/navigation/sync', { method: 'POST' }),
    getLogs: () => request<LogListItem[]>('/api/logs'),
    getLog: (id: string | number) => request<LogDetail>(`/api/logs/${id}`),
    getSystems: () => request<StarSystem[]>('/api/world/systems'),
    getMap: () => request<MapPayload>('/api/world/map'),
    getPrompts: () => request<PromptSettings>('/api/settings/prompts'),
    getSimulationSettings: () => request<SimulationSettings>('/api/settings/simulation'),
    saveSimulationSettings: (payload: SimulationSettingsUpdate) =>
      request<SimulationSettings>('/api/settings/simulation', { method: 'PATCH', body: JSON.stringify(payload) }),
    savePrompts: (payload: Pick<PromptSettings, 'probe_profile' | 'action_policy' | 'log_writer_style'>) =>
      request<PromptSettings>('/api/settings/prompts', { method: 'PUT', body: JSON.stringify(payload) }),
    getClock: () => request<SimulationClock>('/api/simulation/clock'),
    updateClock: (payload: { time_scale?: number; clock_state?: 'running' | 'paused' }) =>
      request<SimulationClock>('/api/simulation/clock', { method: 'PATCH', body: JSON.stringify(payload) }),
    resetClock: () => request<SimulationClock>('/api/simulation/clock/reset', { method: 'POST' }),
    step: () => request<SimulationStep>('/api/simulation/step', { method: 'POST' }),
    tick: () => request<SimulationTick>('/api/simulation/tick', { method: 'POST' }),
    reset: (worldSeed?: string) => request<Probe>('/api/simulation/reset', { method: 'POST', body: JSON.stringify({ world_seed: worldSeed }) })
  }
}
