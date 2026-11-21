<script setup lang="ts">
// 航行マップ。位置は区間の式・時刻表・軌道要素から毎フレーム計算する（11章）。
import { probePosition } from '~/utils/voyage/motion'
import { AU_KM, norm, sub } from '~/utils/voyage/orbits'
import { simTimeAt } from '~/utils/voyage/timetable'

const DEBUG_CHECK_MS = 10_000

const api = useApi()
const voyage = useVoyageStore()
const hud = useVoyageHud()
const debug = ref<{ diffKm: number | null; lastCorrection: number | null }>({ diffKm: null, lastCorrection: null })

// 12章「位置のずれを見る」：同じ現実の時刻で、フロントとバックが計算した位置の差
async function checkBackend() {
  const data = voyage.sync
  if (!data) return
  // 送る ISO 時刻はミリ秒未満を落とすので、フロントも同じ時刻で計算する
  const realIso = new Date(voyage.now()).toISOString()
  const realMs = Date.parse(realIso)
  try {
    const back = await api.getVoyagePosition(realIso)
    const front = probePosition(data.legs, data.start_position_au, simTimeAt(data.timetable, realMs)).position
    debug.value = { ...debug.value, diffKm: norm(sub(front, back.position_au)) * AU_KM }
  } catch (err) {
    console.warn('[voyage] position check failed', err)
  }
}

let debugTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  debugTimer = setInterval(checkBackend, DEBUG_CHECK_MS)
})
onBeforeUnmount(() => {
  if (debugTimer) clearInterval(debugTimer)
})
</script>

<template>
  <main class="page">
    <h1>航行マップ</h1>
    <div v-if="voyage.error" class="error">{{ voyage.error }}</div>
    <section v-if="hud.ready" class="voyage-hud">
      <span>SIM {{ hud.sim }}</span>
      <span>→ {{ hud.target }}<template v-if="hud.legIndex !== null">（区間 {{ hud.legIndex }}）</template></span>
      <span>{{ hud.state }}・{{ hud.speed }}</span>
      <span>太陽から {{ hud.sunAu }}</span>
      <span>次の場面: {{ hud.next }}（{{ hud.mode }}）</span>
    </section>
    <div class="voyage-map-frame">
      <ClientOnly>
        <VoyageMap v-if="voyage.sync" :sync="voyage.sync" :now="voyage.now" @correction="(size) => (debug.lastCorrection = size)" />
      </ClientOnly>
    </div>
    <section v-if="voyage.sync" class="voyage-debug">
      <span>時計の差 {{ voyage.offsetMs.toFixed(0) }} ms</span>
      <span>フロントとバックの位置の差 {{ debug.diffKm === null ? '-' : `${debug.diffKm.toFixed(3)} km` }}</span>
      <span>最後の補正 {{ debug.lastCorrection === null ? '-' : `${debug.lastCorrection.toFixed(3)} 表示単位` }}</span>
    </section>
    <VoyageAdminPanel />
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
.voyage-map-frame {
  height: 70vh;
  min-height: 420px;
  border: 1px solid #1c2a44;
  border-radius: 6px;
  overflow: hidden;
}
</style>
