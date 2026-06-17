import { defineStore } from 'pinia'
import type { LogListItem, MapPayload, Probe, ProbeNavigation, PromptSettings, SimulationClock, SimulationSettings, SimulationSettingsUpdate, SimulationStep, SimulationTick, StarSystem } from '~/types/api'

export const useMissionStore = defineStore('mission', () => {
  const probe = ref<Probe | null>(null)
  const logs = ref<LogListItem[]>([])
  const systems = ref<StarSystem[]>([])
  const map = ref<MapPayload | null>(null)
  const prompts = ref<PromptSettings | null>(null)
  const clock = ref<SimulationClock | null>(null)
  const simulationSettings = ref<SimulationSettings | null>(null)
  const navigation = ref<ProbeNavigation | null>(null)
  const mapRevision = ref(0)
  const sceneRevision = ref(0)
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
      navigation.value = probeData.navigation ?? null
      logs.value = logsData
      systems.value = systemsData
      map.value = mapData
      if (mapData.probe.navigation) {
        navigation.value = mapData.probe.navigation
        probe.value = { ...probeData, navigation: mapData.probe.navigation }
      }
      mapRevision.value += 1
      if (mapRevision.value === 1) sceneRevision.value += 1
      await refreshClock()
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
      navigation.value = lastTick.value.probe.navigation ?? null
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
      if (mapData.probe.navigation) {
        navigation.value = mapData.probe.navigation
        probe.value = { ...lastTick.value.probe, navigation: mapData.probe.navigation }
      }
      mapRevision.value += 1
      await refreshClock()
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

  async function refreshClock() {
    clock.value = await api.getClock()
    try {
      const navigationData = await api.getProbeNavigation()
      navigation.value = navigationData
      if (probe.value) {
        probe.value = { ...probe.value, navigation: navigationData }
      }
    } catch {
      // Clock refresh is used by the HUD; keep it resilient if navigation is not initialized yet.
    }
  }

  async function loadSimulationSettings() {
    simulationSettings.value = await api.getSimulationSettings()
  }

  async function saveSimulationSettings(payload: SimulationSettingsUpdate) {
    loading.value = true
    error.value = null
    try {
      simulationSettings.value = await api.saveSimulationSettings(payload)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function setClockState(clock_state: 'running' | 'paused') {
    clock.value = await api.updateClock({ clock_state })
  }

  async function setTimeScale(time_scale: number) {
    clock.value = await api.updateClock({ time_scale, clock_state: time_scale === 0 ? 'paused' : 'running' })
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
    sceneRevision.value += 1
  }

  return {
    probe,
    logs,
    systems,
    map,
    prompts,
    clock,
    simulationSettings,
    navigation,
    mapRevision,
    sceneRevision,
    loading,
    error,
    lastStep,
    lastTick,
    cruiseRunning,
    lastEvent,
    latestGeneratedLog,
    loadAll,
    loadPrompts,
    refreshClock,
    loadSimulationSettings,
    saveSimulationSettings,
    savePrompts,
    setClockState,
    setTimeScale,
    runStep,
    runTick,
    startCruise,
    stopCruise,
    reset
  }
})
