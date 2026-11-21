import { legArriveMs, legDistanceKm, probePosition, speedAt, speedStateAt, travelledKm } from '~/utils/voyage/motion'
import { AU_KM, bodyPosition, isoToMs, norm, sub } from '~/utils/voyage/orbits'
import { simTimeAt } from '~/utils/voyage/timetable'

const UPDATE_MS = 250

export type VoyageHud = {
  ready: boolean
  sim: string
  target: string
  legIndex: number | null
  state: string
  speed: string
  remaining: string
  progress: number
  sunAu: string
  earthKm: string
  next: string
  mode: '自動' | '手動'
  paused: boolean
}

const EMPTY: VoyageHud = {
  ready: false, sim: '-', target: '-', legIndex: null, state: '-', speed: '-', remaining: '-',
  progress: 0, sunAu: '-', earthKm: '-', next: '-', mode: '手動', paused: false,
}

export const formatUtc = (ms: number) => `${new Date(ms).toISOString().slice(0, 19).replace('T', ' ')} UTC`

function duration(seconds: number): string {
  if (seconds <= 0) return '到着'
  if (seconds < 3600) return `約${Math.max(1, Math.round(seconds / 60))}分`
  if (seconds < 48 * 3600) return `約${(seconds / 3600).toFixed(1)}時間`
  return `約${(seconds / 86_400).toFixed(1)}日`
}

/** 表示用の今の値（シミュレーション時刻、区間、速度、距離、次の場面）を 250ms ごとに計算する。 */
export function useVoyageHud() {
  const voyage = useVoyageStore()
  const hud = ref<VoyageHud>({ ...EMPTY })
  let timer: ReturnType<typeof setInterval> | null = null

  function update() {
    const data = voyage.sync
    if (!data) return
    const simMs = simTimeAt(data.timetable, voyage.now())
    const { position, leg } = probePosition(data.legs, data.start_position_au, simMs)
    const bodies = new Map(data.bodies.map((b) => [b.id, b]))
    const earth = bodies.get('earth')
    const earthKm = earth ? norm(sub(position, bodyPosition(bodies, earth, simMs))) * AU_KM : null
    const upcoming = data.timetable.find((p) => !p.published)
    const mode = data.clock.mode === 'auto' ? '自動' : '手動'
    hud.value = {
      ready: true,
      sim: formatUtc(simMs),
      target: leg ? (bodies.get(leg.target_id)?.name ?? leg.target_id) : '出発前',
      legIndex: leg?.index ?? null,
      state: leg ? speedStateAt(leg.profile, simMs) : '停止',
      speed: leg ? `毎秒 ${speedAt(leg.profile, simMs).toLocaleString('ja-JP', { maximumFractionDigits: 1 })} km` : '毎秒 0 km',
      remaining: leg ? duration((legArriveMs(leg.profile) - simMs) / 1000) : '-',
      progress: leg ? Math.min(1, travelledKm(leg.profile, simMs) / Math.max(legDistanceKm(leg.profile), 1e-9)) : 0,
      sunAu: `${norm(position).toFixed(3)} AU`,
      earthKm: earthKm === null ? '-' : `${Math.round(earthKm).toLocaleString('ja-JP')} km`,
      next: data.clock.paused
        ? '一時停止中'
        : upcoming
          ? `${upcoming.label}（公開予定 ${formatUtc(isoToMs(upcoming.real_at))}）`
          : 'なし（航路の端）',
      mode,
      paused: data.clock.paused,
    }
  }

  onMounted(() => {
    update()
    timer = setInterval(update, UPDATE_MS)
  })
  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
  })
  return hud
}
