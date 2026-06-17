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
  const navigationSyncTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const lastEvent = ref<SimulationTick['event'] | null>(null)
  const latestGeneratedLog = ref<LogListItem | null>(null)
  const api = useApi()

  function applyNavigationSnapshot(navigationData: ProbeNavigation) {
    navigation.value = navigationData
    if (probe.value) {
      probe.value = { ...probe.value, navigation: navigationData }
    }
    if (map.value) {
      const displayPosition = navigationData.display_position
      map.value = {
        ...map.value,
        probe: {
          ...map.value.probe,
          x: displayPosition?.x ?? map.value.probe.x,
          y: displayPosition?.y ?? map.value.probe.y,
          z: displayPosition?.z ?? map.value.probe.z,
          target_id: navigationData.destination_system_id ?? map.value.probe.target_id,
          navigation: navigationData
        }
      }
      mapRevision.value += 1
    }
  }

  function applyClockSnapshot(clockData: SimulationClock) {
    clock.value = clockData
    if (map.value) {
      map.value = {
        ...map.value,
        clock: {
          simulation_datetime: clockData.simulation_datetime,
          time_scale: clockData.time_scale,
          clock_state: clockData.clock_state
        }
      }
    }
  }

  function hasActiveNavigation() {
    return Boolean(navigation.value?.active || map.value?.probe.navigation?.active || probe.value?.target_id)
  }

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
        applyNavigationSnapshot(mapData.probe.navigation)
      }
      mapRevision.value += 1
      if (mapRevision.value === 1) sceneRevision.value += 1
      if (hasActiveNavigation()) startNavigationSync()
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
        applyNavigationSnapshot(mapData.probe.navigation)
      }
      mapRevision.value += 1
      if (hasActiveNavigation()) startNavigationSync()
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

  function startNavigationSync() {
    if (navigationSyncTimer.value) return
    navigationSyncTimer.value = setInterval(() => {
      void syncNavigationState()
    }, 15000)
  }

  function stopNavigationSync() {
    if (navigationSyncTimer.value) {
      clearInterval(navigationSyncTimer.value)
      navigationSyncTimer.value = null
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
    applyClockSnapshot(await api.getClock())
  }

  async function syncNavigationState() {
    if (!hasActiveNavigation()) {
      stopNavigationSync()
      return
    }
    try {
      const navigationData = await api.syncProbeNavigation()
      applyNavigationSnapshot(navigationData)
      if (!navigationData.active) stopNavigationSync()
    } catch {
      // Navigation sync is opportunistic; ticks and map refreshes still carry authoritative state.
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
    applyClockSnapshot(await api.updateClock({ clock_state }))
  }

  async function setTimeScale(time_scale: number) {
    applyClockSnapshot(await api.updateClock({ time_scale, clock_state: time_scale === 0 ? 'paused' : 'running' }))
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
    stopNavigationSync()
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
    syncNavigationState,
    startNavigationSync,
    stopNavigationSync,
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
