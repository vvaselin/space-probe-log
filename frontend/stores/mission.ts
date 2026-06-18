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
  const tickTimer = ref<ReturnType<typeof setTimeout> | null>(null)
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
      const navigationActive = navigationData.active && navigationData.phase !== 'arrived'
      map.value = {
        ...map.value,
        route_prediction: navigationActive ? map.value.route_prediction : null,
        probe: {
          ...map.value.probe,
          x: displayPosition?.x ?? map.value.probe.x,
          y: displayPosition?.y ?? map.value.probe.y,
          z: displayPosition?.z ?? map.value.probe.z,
          target_id: navigationActive ? navigationData.destination_system_id : null,
          navigation: navigationData
        }
      }
      mapRevision.value += 1
    }
  }

  function applyClockSnapshot(clockData: SimulationClock) {
    clock.value = clockData
    if (probe.value) {
      probe.value = {
        ...probe.value,
        mission_clock: clockData.mission_clock,
        sim_timestamp: clockData.simulation_datetime
      }
    }
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

  function cruiseTimeScale() {
    const currentScale = clock.value?.time_scale ?? 0
    if (currentScale > 0) return currentScale
    return simulationSettings.value?.time_scale_presets.find((preset) => preset > 0) ?? 500000
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

  async function refreshLogs() {
    loading.value = true
    error.value = null
    try {
      logs.value = await api.getLogs()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function refreshMap() {
    loading.value = true
    error.value = null
    try {
      const [probeData, systemsData, mapData, clockData] = await Promise.all([
        api.getProbe(),
        api.getSystems(),
        api.getMap(),
        api.getClock()
      ])
      probe.value = probeData
      navigation.value = probeData.navigation ?? mapData.probe.navigation ?? null
      systems.value = systemsData
      map.value = mapData
      if (mapData.probe.navigation) {
        applyNavigationSnapshot(mapData.probe.navigation)
      }
      mapRevision.value += 1
      applyClockSnapshot(clockData)
      if (hasActiveNavigation()) startNavigationSync()
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

  async function runTick(): Promise<boolean> {
    if (loading.value) return false
    loading.value = true
    error.value = null
    try {
      const tick = await api.tick()
      lastTick.value = tick
      probe.value = tick.probe
      navigation.value = tick.probe.navigation ?? null
      lastEvent.value = tick.event
      latestGeneratedLog.value = tick.log
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
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
      return false
    } finally {
      loading.value = false
    }
  }

  function stopCruiseTimer() {
    cruiseRunning.value = false
    if (tickTimer.value) {
      clearTimeout(tickTimer.value)
      tickTimer.value = null
    }
  }

  function scheduleCruiseTick(delayMs = 1800) {
    if (!cruiseRunning.value || tickTimer.value) return
    tickTimer.value = setTimeout(async () => {
      tickTimer.value = null
      if (!cruiseRunning.value) return
      const succeeded = await runTick()
      scheduleCruiseTick(succeeded ? 1800 : 5000)
    }, delayMs)
  }

  function reconcileCruiseTimer() {
    const shouldRun = clock.value?.clock_state === 'running' && (clock.value?.time_scale ?? 0) > 0
    if (!shouldRun) {
      stopCruiseTimer()
      return
    }
    cruiseRunning.value = true
    scheduleCruiseTick()
  }

  async function startCruise() {
    if (tickTimer.value) return
    error.value = null
    try {
      cruiseRunning.value = true
      const timeScale = cruiseTimeScale()
      if (clock.value && (clock.value.clock_state === 'paused' || clock.value.time_scale === 0)) {
        applyClockSnapshot({ ...clock.value, time_scale: timeScale, clock_state: 'running' })
      }
      const updatedClock = await api.updateClock({ time_scale: timeScale, clock_state: 'running' })
      applyClockSnapshot(updatedClock)
      if (hasActiveNavigation()) await syncNavigationState()
      await runTick()
      scheduleCruiseTick()
    } catch (err) {
      stopCruiseTimer()
      error.value = err instanceof Error ? err.message : 'API error'
    }
  }

  async function stopCruise() {
    error.value = null
    try {
      stopCruiseTimer()
      if (clock.value && clock.value.clock_state !== 'paused') {
        applyClockSnapshot({ ...clock.value, clock_state: 'paused' })
      }
      const updatedClock = await api.updateClock({ clock_state: 'paused' })
      applyClockSnapshot(updatedClock)
      if (hasActiveNavigation()) await syncNavigationState()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
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
    reconcileCruiseTimer()
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
    if (clock.value && clock_state === 'paused') {
      stopCruiseTimer()
      applyClockSnapshot({ ...clock.value, clock_state })
    }
    const updatedClock = await api.updateClock({ clock_state })
    applyClockSnapshot(updatedClock)
    if (hasActiveNavigation()) await syncNavigationState()
  }

  async function setTimeScale(time_scale: number) {
    const clock_state = time_scale === 0 ? 'paused' : clock.value?.clock_state ?? 'running'
    if (clock.value && clock_state === 'paused') {
      stopCruiseTimer()
      applyClockSnapshot({ ...clock.value, time_scale, clock_state })
    }
    const updatedClock = await api.updateClock({ time_scale, clock_state })
    applyClockSnapshot(updatedClock)
    if (hasActiveNavigation()) await syncNavigationState()
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
    stopCruiseTimer()
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
    refreshLogs,
    refreshMap,
    loadPrompts,
    refreshClock,
    syncNavigationState,
    startNavigationSync,
    stopNavigationSync,
    stopCruiseTimer,
    reconcileCruiseTimer,
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
