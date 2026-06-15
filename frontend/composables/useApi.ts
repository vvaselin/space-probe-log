import type { LogDetail, LogListItem, MapPayload, Probe, PromptSettings, SimulationStep, StarSystem } from '~/types/api'

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
    getLogs: () => request<LogListItem[]>('/api/logs'),
    getLog: (id: string | number) => request<LogDetail>(`/api/logs/${id}`),
    getSystems: () => request<StarSystem[]>('/api/world/systems'),
    getMap: () => request<MapPayload>('/api/world/map'),
    getPrompts: () => request<PromptSettings>('/api/settings/prompts'),
    savePrompts: (payload: Pick<PromptSettings, 'probe_profile' | 'action_policy' | 'log_writer_style'>) =>
      request<PromptSettings>('/api/settings/prompts', { method: 'PUT', body: JSON.stringify(payload) }),
    step: () => request<SimulationStep>('/api/simulation/step', { method: 'POST' }),
    reset: (worldSeed?: string) => request<Probe>('/api/simulation/reset', { method: 'POST', body: JSON.stringify({ world_seed: worldSeed }) })
  }
}
