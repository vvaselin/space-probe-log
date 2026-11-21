import { defineStore } from 'pinia'
import { isoToMs } from '~/utils/voyage/orbits'
import type { VoyageLogItem, VoyageSync } from '~/utils/voyage/types'

const REFRESH_MS = 60_000 // 時計合わせと、手動で進めた場面の取り込み
const PAUSED_REFRESH_MS = 10_000 // 一時停止中は、再開にすぐ気づけるよう短い間隔で取り直す
const SLEW_MS = 3_000 // 時計の差が変わった時に、この時間をかけて寄せる

/**
 * 航行（app/voyage）の同期の材料とログ。画面全体で1つだけ持ち、app.vue が取り直しを始める。
 * 時計の差は、往復にかかった時間の半分を足して測り、一気には合わせない（11章）。
 */
export const useVoyageStore = defineStore('voyage', () => {
  const api = useApi()
  const sync = shallowRef<VoyageSync | null>(null)
  const logs = ref<VoyageLogItem[]>([])
  const error = ref<string | null>(null)
  const offsetMs = ref(0)
  let slewFrom = 0
  let slewTarget = 0
  let slewStart = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  const currentOffset = () => {
    const k = Math.min(1, Math.max(0, (Date.now() - slewStart) / SLEW_MS))
    return slewFrom + (slewTarget - slewFrom) * k
  }

  /** サーバーの時計での今（UNIXミリ秒）。 */
  const now = () => Date.now() + currentOffset()

  async function refreshLogs() {
    try {
      logs.value = await api.getVoyageLogs()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function refresh() {
    try {
      const sent = Date.now()
      const data = await api.getVoyageSync()
      const received = Date.now()
      const measured = isoToMs(data.server_time) + (received - sent) / 2 - received
      slewFrom = sync.value === null ? measured : currentOffset()
      slewTarget = measured
      slewStart = received
      offsetMs.value = measured
      const published = data.clock.last_published_at !== sync.value?.clock.last_published_at
      sync.value = data
      error.value = null
      if (published) await refreshLogs()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      schedule()
    }
  }

  // 次の公開の予定が近ければ、その少し後に取り直す（新しい区間の式を受け取るため）
  function schedule() {
    if (timer) clearTimeout(timer)
    const upcoming = sync.value?.timetable.find((p) => !p.published)
    const untilUpcoming = upcoming ? isoToMs(upcoming.real_at) - now() + 2_000 : Infinity
    const idle = sync.value?.clock.paused ? PAUSED_REFRESH_MS : REFRESH_MS
    // 予定を過ぎてまだ公開されていない時は、ふだんの間隔で待つ
    timer = setTimeout(refresh, untilUpcoming > 0 ? Math.max(1_000, Math.min(idle, untilUpcoming)) : idle)
  }

  function start() {
    if (!timer) void refresh()
  }

  function stop() {
    if (timer) clearTimeout(timer)
    timer = null
  }

  return { sync, logs, error, offsetMs, now, refresh, refreshLogs, start, stop }
})
