import { isoToMs } from '~/utils/voyage/orbits'
import type { VoyageSync } from '~/utils/voyage/types'

const REFRESH_MS = 60_000 // 時計合わせと、手動で進めた場面の取り込み
const PAUSED_REFRESH_MS = 10_000
const SLEW_MS = 3_000 // 時計の差が変わった時に、この時間をかけて寄せる

/**
 * サーバーの時計に合わせた「今」と、同期の材料（区間の式、時刻表、軌道要素）。
 * 時計の差は、往復にかかった時間の半分を足して測り、一気には合わせない（11章）。
 */
export function useVoyageClock() {
  const api = useApi()
  const sync = shallowRef<VoyageSync | null>(null)
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

  async function refresh() {
    try {
      const sent = Date.now()
      const data = await api.getVoyageSync()
      const received = Date.now()
      const measured = isoToMs(data.server_time) + (received - sent) / 2 - received
      if (sync.value === null) {
        slewFrom = measured
      } else {
        slewFrom = currentOffset()
      }
      slewTarget = measured
      slewStart = received
      offsetMs.value = measured
      sync.value = data
      error.value = null
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
    // 一時停止中は、再開にすぐ気づけるよう短い間隔で取り直す
    const idle = sync.value?.clock.paused ? PAUSED_REFRESH_MS : REFRESH_MS
    // 予定を過ぎてまだ公開されていない時は、ふだんの間隔で待つ
    timer = setTimeout(refresh, untilUpcoming > 0 ? Math.max(1_000, Math.min(idle, untilUpcoming)) : idle)
  }

  onMounted(refresh)
  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })

  return { sync, error, offsetMs, now, refresh }
}
