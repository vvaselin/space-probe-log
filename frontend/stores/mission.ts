import { defineStore } from 'pinia'
import type { LogListItem, MapPayload, Probe, PromptSettings, SimulationStep, SimulationTick, StarSystem } from '~/types/api'

export const useMissionStore = defineStore('mission', () => {
  const probe = ref<Probe | null>(null)
  const logs = ref<LogListItem[]>([])
  const systems = ref<StarSystem[]>([])
  const map = ref<MapPayload | null>(null)
  const prompts = ref<PromptSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastStep = ref<SimulationStep | null>(null)
  const lastTick = ref<SimulationTick | null>(null)
  const cruiseRunning = ref(false)
  const tickTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const lastEvent = ref<SimulationTick['event'] | null>(null)
  const latestGeneratedLog = ref<LogListItem | null>(null)
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

  async function runTick() {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      lastTick.value = await api.tick()
      probe.value = lastTick.value.probe
      lastEvent.value = lastTick.value.event
      latestGeneratedLog.value = lastTick.value.log
      const [logsData, systemsData, mapData] = await Promise.all([
        api.getLogs(),
        api.getSystems(),
        api.getMap()
      ])
      logs.value = logsData
      systems.value = systemsData
      map.value = mapData
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
      stopCruise()
    } finally {
      loading.value = false
    }
  }

  function startCruise() {
    if (tickTimer.value) return
    cruiseRunning.value = true
    void runTick()
    tickTimer.value = setInterval(() => {
      void runTick()
    }, 1800)
  }

  function stopCruise() {
    cruiseRunning.value = false
    if (tickTimer.value) {
      clearInterval(tickTimer.value)
      tickTimer.value = null
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
    stopCruise()
    await api.reset()
    await loadAll()
  }

  return {
    probe,
    logs,
    systems,
    map,
    prompts,
    loading,
    error,
    lastStep,
    lastTick,
    cruiseRunning,
    lastEvent,
    latestGeneratedLog,
    loadAll,
    loadPrompts,
    savePrompts,
    runStep,
    runTick,
    startCruise,
    stopCruise,
    reset
  }
})
