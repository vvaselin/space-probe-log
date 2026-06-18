import { defineStore } from 'pinia'
import type { AdminSession, LogListItem, MapPayload, Probe, ProbeNavigation, PromptSettings, SimulationClock, SimulationSettings, SimulationSettingsUpdate, SimulationStep, SimulationTick, StarSystem } from '~/types/api'

export const useMissionStore = defineStore('mission', () => {
  const probe = ref<Probe | null>(null)
  const logs = ref<LogListItem[]>([])
  const systems = ref<StarSystem[]>([])
  const map = ref<MapPayload | null>(null)
  const prompts = ref<PromptSettings | null>(null)
  const clock = ref<SimulationClock | null>(null)
  const simulationSettings = ref<SimulationSettings | null>(null)
  const navigation = ref<ProbeNavigation | null>(null)
  const adminSession = ref<AdminSession | null>(null)
  const mapRevision = ref(0)
  const sceneRevision = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastStep = ref<SimulationStep | null>(null)
  const lastEvent = ref<SimulationTick['event'] | null>(null)
  const latestGeneratedLog = ref<LogListItem | null>(null)
  const api = useApi()
  let dashboardRefresh: Promise<void> | null = null

  const isAdmin = computed(() => Boolean(adminSession.value?.authenticated))

  function adminToken() {
    const token = adminSession.value?.csrf_token
    if (!token) throw new Error('管理者ログインが必要です')
    return token
  }

  function applyNavigationSnapshot(navigationData: ProbeNavigation) {
    navigation.value = navigationData
    if (probe.value) probe.value = { ...probe.value, navigation: navigationData }
    if (!map.value) return
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
        navigation: navigationData,
      },
    }
    mapRevision.value += 1
  }

  function applyClockSnapshot(clockData: SimulationClock) {
    clock.value = clockData
    if (probe.value) {
      probe.value = { ...probe.value, mission_clock: clockData.mission_clock, sim_timestamp: clockData.simulation_datetime }
    }
    if (map.value) {
      map.value = {
        ...map.value,
        clock: {
          simulation_datetime: clockData.simulation_datetime,
          time_scale: clockData.time_scale,
          clock_state: clockData.clock_state,
        },
      }
    }
  }

  function applyDashboardData(probeData: Probe, logsData: LogListItem[], mapData: MapPayload, clockData: SimulationClock) {
    const previousLatestId = logs.value[0]?.id
    probe.value = probeData
    navigation.value = probeData.navigation ?? mapData.probe.navigation ?? null
    logs.value = logsData
    map.value = mapData
    if (mapData.probe.navigation) applyNavigationSnapshot(mapData.probe.navigation)
    if (previousLatestId !== undefined && logsData[0] && logsData[0].id !== previousLatestId) {
      latestGeneratedLog.value = logsData[0]
    }
    mapRevision.value += 1
    applyClockSnapshot(clockData)
  }

  async function loadAll() {
    loading.value = true
    error.value = null
    const firstScene = map.value === null
    try {
      const [probeData, logsData, systemsData, mapData, clockData] = await Promise.all([
        api.getProbe(), api.getLogs(), api.getSystems(), api.getMap(), api.getClock(),
      ])
      systems.value = systemsData
      applyDashboardData(probeData, logsData, mapData, clockData)
      if (firstScene) sceneRevision.value += 1
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function refreshDashboard() {
    if (dashboardRefresh) return dashboardRefresh
    dashboardRefresh = (async () => {
      try {
        const [probeData, logsData, mapData, clockData] = await Promise.all([
          api.getProbe(), api.getLogs(), api.getMap(), api.getClock(),
        ])
        applyDashboardData(probeData, logsData, mapData, clockData)
      } catch (err) {
        error.value = err instanceof Error ? err.message : 'API error'
      } finally {
        dashboardRefresh = null
      }
    })()
    return dashboardRefresh
  }

  async function refreshLogs() {
    try {
      logs.value = await api.getLogs()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    }
  }

  async function refreshMap() {
    loading.value = true
    error.value = null
    try {
      const [probeData, systemsData, mapData, clockData] = await Promise.all([
        api.getProbe(), api.getSystems(), api.getMap(), api.getClock(),
      ])
      probe.value = probeData
      systems.value = systemsData
      navigation.value = probeData.navigation ?? mapData.probe.navigation ?? null
      map.value = mapData
      if (mapData.probe.navigation) applyNavigationSnapshot(mapData.probe.navigation)
      mapRevision.value += 1
      applyClockSnapshot(clockData)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'API error'
    } finally {
      loading.value = false
    }
  }

  async function refreshClock() {
    applyClockSnapshot(await api.getClock())
  }

  async function restoreAdminSession() {
    try {
      adminSession.value = await api.getAdminSession()
    } catch {
      adminSession.value = null
    }
  }

  async function loginAdmin(username: string, password: string) {
    adminSession.value = await api.loginAdmin({ username, password })
  }

  async function logoutAdmin() {
    if (!adminSession.value) return
    await api.logoutAdmin(adminToken())
    adminSession.value = null
  }

  function cruiseTimeScale() {
    const currentScale = clock.value?.time_scale ?? 0
    if (currentScale > 0) return currentScale
    return simulationSettings.value?.time_scale_presets.find((preset) => preset > 0) ?? 500000
  }

  async function startCruise() {
    const updatedClock = await api.updateClock({ time_scale: cruiseTimeScale(), clock_state: 'running' }, adminToken())
    applyClockSnapshot(updatedClock)
    await refreshDashboard()
  }

  async function stopCruise() {
    if (clock.value) applyClockSnapshot({ ...clock.value, clock_state: 'paused' })
    const updatedClock = await api.updateClock({ clock_state: 'paused' }, adminToken())
    applyClockSnapshot(updatedClock)
  }

  async function setClockState(clockState: 'running' | 'paused') {
    const updatedClock = await api.updateClock({ clock_state: clockState }, adminToken())
    applyClockSnapshot(updatedClock)
  }

  async function setTimeScale(timeScale: number) {
    const clockState = timeScale === 0 ? 'paused' : clock.value?.clock_state ?? 'running'
    const updatedClock = await api.updateClock({ time_scale: timeScale, clock_state: clockState }, adminToken())
    applyClockSnapshot(updatedClock)
  }

  async function runStep() {
    lastStep.value = await api.step(adminToken())
    await loadAll()
  }

  async function loadPrompts() {
    prompts.value = await api.getPrompts()
  }

  async function loadSimulationSettings() {
    simulationSettings.value = await api.getSimulationSettings()
  }

  async function saveSimulationSettings(payload: SimulationSettingsUpdate) {
    simulationSettings.value = await api.saveSimulationSettings(payload, adminToken())
  }

  async function savePrompts(payload: Pick<PromptSettings, 'probe_profile' | 'action_policy' | 'log_writer_style'>) {
    prompts.value = await api.savePrompts(payload, adminToken())
  }

  async function reset() {
    await api.reset(adminToken())
    await loadAll()
    sceneRevision.value += 1
  }

  return {
    probe, logs, systems, map, prompts, clock, simulationSettings, navigation, adminSession, isAdmin,
    mapRevision, sceneRevision, loading, error, lastStep, lastEvent, latestGeneratedLog,
    loadAll, refreshDashboard, refreshLogs, refreshMap, refreshClock,
    restoreAdminSession, loginAdmin, logoutAdmin,
    loadPrompts, loadSimulationSettings, saveSimulationSettings, savePrompts,
    setClockState, setTimeScale, runStep, startCruise, stopCruise, reset,
  }
})
