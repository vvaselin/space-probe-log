<script setup lang="ts">
// 再設計版の航行（app/voyage）。既存の /map とは別の画面で、切り替えは後で行う。
import { probePosition, speedAt } from '~/utils/voyage/motion'
import { AU_KM, isoToMs, norm, sub } from '~/utils/voyage/orbits'
import { simTimeAt } from '~/utils/voyage/timetable'

const DEBUG_CHECK_MS = 10_000

const api = useApi()
const { sync, error, offsetMs, now, refresh } = useVoyageClock()
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
  const mode = data.clock.mode === 'auto' ? '自動' : '手動'
  hud.value = {
    sim: formatTime(simMs),
    leg: leg ? `→ ${names.get(leg.target_id) ?? leg.target_id}（区間 ${leg.index}）` : '出発前',
    speed: leg ? `毎秒 ${speedAt(leg.profile, simMs).toLocaleString('ja-JP', { maximumFractionDigits: 1 })} km` : '0 km/s',
    next: data.clock.paused
      ? `一時停止中（${mode}）`
      : upcoming
        ? `${upcoming.label}（${mode}・公開予定 ${formatTime(isoToMs(upcoming.real_at))}）`
        : 'なし（航路の端）',
  }
}

// 管理者の操作（10章、12章）
const store = useMissionStore()
const busy = ref(false)
const adminMessage = ref<string | null>(null)
const INTERVAL_PRESETS = [
  { label: '24時間', seconds: 86_400 },
  { label: '1時間', seconds: 3_600 },
  { label: '5分', seconds: 300 },
  { label: '1分', seconds: 60 },
]
const customInterval = ref<number | null>(null)

async function adminAction(label: string, action: (csrf: string) => Promise<unknown>) {
  const csrf = store.adminSession?.csrf_token
  if (!csrf) {
    adminMessage.value = '管理者ログインが必要です'
    return
  }
  busy.value = true
  try {
    const result = await action(csrf)
    adminMessage.value = label === '次の場面へ進める' && result && typeof result === 'object' && 'log_number' in result
      ? `LOG #${String(result.log_number).padStart(3, '0')} を書いた`
      : `${label}：完了`
    await refresh()
  } catch (err) {
    adminMessage.value = `${label}：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busy.value = false
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
    <section v-if="sync && store.isAdmin" class="voyage-admin">
      <span>公開 {{ sync.clock.mode === 'auto' ? '自動' : '手動' }}・間隔 {{ sync.clock.interval_seconds.toLocaleString('ja-JP') }} 秒</span>
      <button type="button" :disabled="busy || sync.clock.ended" @click="adminAction('次の場面へ進める', api.stepVoyage)">
        次の場面へ進める
      </button>
      <button v-if="sync.clock.paused" type="button" :disabled="busy" @click="adminAction('再開', api.resumeVoyage)">再開</button>
      <button v-else type="button" :disabled="busy" @click="adminAction('一時停止', api.pauseVoyage)">一時停止</button>
      <button
        type="button"
        :disabled="busy"
        @click="adminAction('モードの切り替え', (csrf) => api.updateVoyageClock({ mode: sync?.clock.mode === 'auto' ? 'manual' : 'auto' }, csrf))"
      >
        {{ sync.clock.mode === 'auto' ? '手動にする' : '自動にする' }}
      </button>
      <span class="voyage-admin__intervals">
        間隔:
        <button
          v-for="preset in INTERVAL_PRESETS"
          :key="preset.seconds"
          type="button"
          :disabled="busy"
          @click="adminAction('間隔の変更', (csrf) => api.updateVoyageClock({ interval_seconds: preset.seconds }, csrf))"
        >
          {{ preset.label }}
        </button>
        <input v-model.number="customInterval" type="number" min="1" placeholder="秒" />
        <button
          type="button"
          :disabled="busy || !customInterval || customInterval < 1"
          @click="adminAction('間隔の変更', (csrf) => api.updateVoyageClock({ interval_seconds: customInterval ?? undefined }, csrf))"
        >
          設定
        </button>
      </span>
      <span v-if="adminMessage">{{ adminMessage }}</span>
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
.voyage-admin {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin: 12px 0;
  font-size: 13px;
}
.voyage-admin__intervals input {
  width: 7em;
}
</style>
