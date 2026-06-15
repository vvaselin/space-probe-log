import { defineStore } from 'pinia'
import type { LogListItem, MapPayload, Probe, PromptSettings, SimulationStep, StarSystem } from '~/types/api'

export const useMissionStore = defineStore('mission', () => {
  const probe = ref<Probe | null>(null)
  const logs = ref<LogListItem[]>([])
  const systems = ref<StarSystem[]>([])
  const map = ref<MapPayload | null>(null)
  const prompts = ref<PromptSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastStep = ref<SimulationStep | null>(null)
  const api = useApi()

  async function loadAll() {
    loading.value = true
    error.value = null
    try {
      const [probeData, logsData, systemsData, mapData] = await Promise.all([
        api.getProbe(),
        api.getLogs(),
        api.getSystems(),
        api.getMap()
      ])
      probe.value = probeData
      logs.value = logsData
      systems.value = systemsData
      map.value = mapData
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function runStep() {
    loading.value = true
    error.value = null
    try {
      lastStep.value = await api.step()
      await loadAll()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function loadPrompts() {
    error.value = null
    try {
      prompts.value = await api.getPrompts()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    }
  }

  async function savePrompts(payload: Pick<PromptSettings, 'probe_profile' | 'action_policy' | 'log_writer_style'>) {
    loading.value = true
    error.value = null
    try {
      prompts.value = await api.savePrompts(payload)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function reset() {
    await api.reset()
    await loadAll()
  }

  return { probe, logs, systems, map, prompts, loading, error, lastStep, loadAll, loadPrompts, savePrompts, runStep, reset }
})
