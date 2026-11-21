<script setup lang="ts">
// 再設計版の航行（app/voyage）。既存の /map とは別の画面で、切り替えは後で行う。
import { probePosition, speedAt } from '~/utils/voyage/motion'
import { AU_KM, isoToMs, norm, sub } from '~/utils/voyage/orbits'
import { simTimeAt } from '~/utils/voyage/timetable'

const DEBUG_CHECK_MS = 10_000

const api = useApi()
const { sync, error, offsetMs, now } = useVoyageClock()
const hud = ref({ sim: '-', leg: '-', speed: '-', next: '-' })
const debug = ref<{ diffKm: number | null; lastCorrection: number | null }>({ diffKm: null, lastCorrection: null })

const formatTime = (ms: number) => `${new Date(ms).toISOString().slice(0, 19).replace('T', ' ')} UTC`

function updateHud() {
  const data = sync.value
  if (!data) return
  const simMs = simTimeAt(data.timetable, now())
  const { leg } = probePosition(data.legs, data.start_position_au, simMs)
  const names = new Map(data.bodies.map((b) => [b.id, b.name]))
  const upcoming = data.timetable.find((p) => !p.published)
  hud.value = {
    sim: formatTime(simMs),
    leg: leg ? `→ ${names.get(leg.target_id) ?? leg.target_id}（区間 ${leg.index}）` : '出発前',
    speed: leg ? `毎秒 ${speedAt(leg.profile, simMs).toLocaleString('ja-JP', { maximumFractionDigits: 1 })} km` : '0 km/s',
    next: upcoming ? `${upcoming.label}（公開予定 ${formatTime(isoToMs(upcoming.real_at))}）` : 'なし（航路の端）',
  }
}

// 12章「位置のずれを見る」：同じ現実の時刻で、フロントとバックが計算した位置の差
async function checkBackend() {
  const data = sync.value
  if (!data) return
  // 送る ISO 時刻はミリ秒未満を落とすので、フロントも同じ時刻で計算する
  const realIso = new Date(now()).toISOString()
  const realMs = Date.parse(realIso)
  try {
    const back = await api.getVoyagePosition(realIso)
    const front = probePosition(data.legs, data.start_position_au, simTimeAt(data.timetable, realMs)).position
    debug.value = { ...debug.value, diffKm: norm(sub(front, back.position_au)) * AU_KM }
  } catch (err) {
    console.warn('[voyage] position check failed', err)
  }
}

let hudTimer: ReturnType<typeof setInterval> | null = null
let debugTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  hudTimer = setInterval(updateHud, 250)
  debugTimer = setInterval(checkBackend, DEBUG_CHECK_MS)
})
onBeforeUnmount(() => {
  if (hudTimer) clearInterval(hudTimer)
  if (debugTimer) clearInterval(debugTimer)
})
</script>

<template>
  <main class="page">
    <h1>航行マップ（再設計版）</h1>
    <div v-if="error" class="error">{{ error }}</div>
    <section v-if="sync" class="voyage-hud">
      <span>SIM {{ hud.sim }}</span>
      <span>{{ hud.leg }}</span>
      <span>{{ hud.speed }}</span>
      <span>次の場面: {{ hud.next }}</span>
    </section>
    <ClientOnly>
      <VoyageMap v-if="sync" :sync="sync" :now="now" @correction="(size) => (debug.lastCorrection = size)" />
    </ClientOnly>
    <section v-if="sync" class="voyage-debug">
      <span>時計の差 {{ offsetMs.toFixed(0) }} ms</span>
      <span>フロントとバックの位置の差 {{ debug.diffKm === null ? '-' : `${debug.diffKm.toFixed(3)} km` }}</span>
      <span>最後の補正 {{ debug.lastCorrection === null ? '-' : `${debug.lastCorrection.toFixed(3)} 表示単位` }}</span>
    </section>
  </main>
</template>

<style scoped>
.voyage-hud,
.voyage-debug {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin: 8px 0;
  font-family: ui-monospace, monospace;
  font-size: 13px;
}
.voyage-debug {
  opacity: 0.7;
}
</style>
