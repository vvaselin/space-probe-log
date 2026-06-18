<script setup lang="ts">
import type { LogDetail, LogListItem } from '~/types/api'

const store = useMissionStore()
const api = useApi()
const selectedLog = ref<LogDetail | null>(null)
const logError = ref<string | null>(null)
const followEnabled = ref(false)
let dashboardTimer: number | null = null

onMounted(async () => {
  await store.loadAll()
  dashboardTimer = window.setInterval(() => {
    if (store.clock?.clock_state === 'running') void store.refreshDashboard()
  }, 2500)
})

onBeforeUnmount(() => {
  if (dashboardTimer !== null) window.clearInterval(dashboardTimer)
})

const mapKey = computed(() => {
  const map = store.map
  if (!map) return 'map-loading'
  return [
    'mission-map',
    store.sceneRevision,
    map.probe.id,
    map.probe.system_id,
    map.probe.target_id ?? 'idle',
    map.systems.length,
  ].join(':')
})

const route = computed(() => store.navigation ?? store.probe?.navigation ?? null)
const missionClock = computed(() => store.clock?.mission_clock ?? store.probe?.mission_clock ?? '2080/05/02 12:00:00 UTC')
const selectedLogBody = computed(() => renderMarkdown(selectedLog.value?.body_markdown ?? ''))
const isCruisePaused = computed(() => store.clock?.clock_state !== 'running')
const routeProgressPercent = computed(() => Math.max(0, Math.min(100, Math.round(route.value?.progress_percent ?? 0))))
const currentSystem = computed(() => store.systems.find((system) => system.id === store.probe?.current_system_id) ?? null)
const currentSystemLabel = computed(() => {
  const systemId = store.probe?.current_system_id ?? '-'
  const systemName = currentSystem.value?.name
  return systemName && systemName.toLowerCase() !== systemId.toLowerCase() ? `${systemName} / ${systemId}` : systemId
})
const locationDetail = computed(() => {
  const galactic = route.value?.galactic_position_pc
  const local = route.value?.local_position_au
  const position = galactic ?? local ?? store.map?.probe ?? null
  if (!position) return null
  const format = (value: number) => Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(4)
  return {
    label: galactic ? 'GALACTIC' : local ? 'LOCAL' : 'MAP',
    value: `X ${format(position.x)}  Y ${format(position.y)}  Z ${format(position.z)}`,
    unit: galactic ? 'pc' : local ? 'AU' : '',
  }
})
const displayPosition = computed(() => route.value?.display_position ?? store.map?.probe ?? null)
const formattedPosition = computed(() => {
  const position = displayPosition.value
  if (!position) return null
  return [position.x, position.y, position.z].map((value) => Number(value).toFixed(4)).join(', ')
})
const visibleLastEventSummary = computed(() => {
  const summary = store.lastEvent?.summary?.trim()
  if (!summary) return null
  const normalize = (value: string) => value.replace(/[。．.\s]+$/g, '').replaceAll(/\s+/g, '')
  return normalize(summary) === normalize(store.probe?.current_mission ?? '') ? null : summary
})

function logClock(log: LogListItem | LogDetail) {
  const clock = log.probe_position?.mission_clock
  return typeof clock === 'string' ? clock : new Date(log.generated_at).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

const phaseLabel = computed(() => {
  switch (route.value?.phase) {
    case 'course_plotted':
      return '航路設定'
    case 'accelerating':
      return '加速中'
    case 'cruising':
      return '巡航中'
    case 'decelerating':
      return '減速中'
    case 'arrived':
      return '到着'
    default:
      return store.probe?.target_id ? '航行中' : '待機'
  }
})

async function resetSimulation() {
  if (window.confirm('ワールド、探査機状態、ログを初期状態にリセットします。実行しますか？')) {
    selectedLog.value = null
    await store.reset()
  }
}

async function openLog(log: LogListItem) {
  logError.value = null
  try {
    selectedLog.value = await api.getLog(log.id)
  } catch (err) {
    logError.value = err instanceof Error ? err.message : 'ログを読み込めませんでした'
  }
}
function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`\s*([^`]+?)\s*`/g, '<code>$1</code>')
}

function renderMarkdown(markdown: string) {
  const blocks: string[] = []
  let paragraph: string[] = []
  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join('<br>')}</p>`)
    paragraph = []
  }

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trimEnd()
    if (!line.trim()) {
      flushParagraph()
      continue
    }
    if (line === '---' || line === '---------------------') {
      flushParagraph()
      blocks.push('<hr>')
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushParagraph()
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    paragraph.push(line)
  }

  flushParagraph()
  return blocks.join('\n')
}
</script>

<template>
  <main class="dashboard-hud">
    <div class="dashboard-map">
      <ClientOnly>
        <SpaceMap
          v-if="store.map"
          :key="mapKey"
          :payload="store.map"
          :paused="store.clock?.clock_state === 'paused'"
          :follow-enabled="followEnabled"
          show-target-callout
          hide-toolbar
        />
      </ClientOnly>
      <div v-if="!store.map && !store.error" class="hud-loading">マップを同期中...</div>
    </div>

    <div v-if="store.error" class="hud-error">{{ store.error }}</div>

    <aside v-if="store.probe" class="hud-panel hud-panel--left">
      <section class="hud-identity">
        <p class="hud-kicker">探査機</p>
        <h1>{{ store.probe.name }}</h1>
        <p class="hud-location">{{ missionClock }}</p>
        <div class="hud-position">
          <strong>{{ currentSystemLabel }}</strong>
          <small v-if="locationDetail">{{ locationDetail.label }} / {{ locationDetail.value }} {{ locationDetail.unit }}</small>
        </div>
        <p v-if="store.probe.target_id" class="hud-target">航行中: {{ store.probe.target_id }}</p>
        <p class="hud-mission">{{ store.probe.current_mission }}</p>
      </section>

      <div class="hud-route">
        <span>{{ route?.destination_name ?? '航路未設定' }}</span>
        <strong>{{ phaseLabel }}</strong>
        <small>速度 {{ (route?.current_speed_km_s ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 }) }} km/s / {{ route?.drive_mode ?? 'conventional' }}</small>
        <small>残距離 {{ (route?.remaining_distance_pc ?? 0).toFixed(4) }} pc / 進捗 {{ routeProgressPercent }}%</small>
        <small v-if="route?.eta_datetime">ETA {{ new Date(route.eta_datetime).toISOString().replace('T', ' ').slice(0, 16) }} UTC</small>
        <div class="hud-route-bar">
          <span :style="{ width: `${routeProgressPercent}%` }" />
        </div>
      </div>
      <p v-if="visibleLastEventSummary" class="hud-last-event">{{ visibleLastEventSummary }}</p>

      <div class="hud-status-list">
        <StatusBar label="エネルギー" :value="store.probe.energy" />
        <StatusBar label="船体" :value="store.probe.hull" />
        <StatusBar label="通信" :value="store.probe.communication" />
        <StatusBar label="センサー" :value="store.probe.sensors" />
        <StatusBar label="推進系" :value="store.probe.propulsion" />
        <StatusBar label="ストレージ" :value="store.probe.storage_used" :max="store.probe.storage_capacity" />
      </div>
    </aside>

    <aside class="hud-panel hud-panel--right">
      <div class="hud-panel-head">
        <h2><span>NAV</span> LOG</h2>
        <NuxtLink to="/logs" class="hud-link">一覧</NuxtLink>
      </div>
      <p v-if="logError" class="error">{{ logError }}</p>
      <button
        v-for="log in store.logs.slice(0, 6)"
        :key="log.id"
        type="button"
        class="hud-log-item"
        :class="{ 'hud-log-item--new': store.latestGeneratedLog?.id === log.id }"
        @click="openLog(log)"
      >
        <span>{{ logClock(log) }} / 信頼度 {{ log.reliability.toFixed(2) }}</span>
        <strong>{{ log.title }}</strong>
        <small>{{ log.summary }}</small>
      </button>
      <p v-if="!store.logs.length && !store.loading" class="muted">ログはまだ生成されていません。</p>
    </aside>

    <div class="hud-controls">
      <button v-if="store.isAdmin && isCruisePaused" :disabled="store.loading" @click="store.startCruise">巡航開始</button>
      <button v-else-if="store.isAdmin" :disabled="store.loading" @click="store.stopCruise">一時停止</button>
      <button class="button-secondary" type="button" :class="{ 'is-active': followEnabled }" @click="followEnabled = !followEnabled">
        {{ followEnabled ? '追尾解除' : '探査機を追尾' }}
      </button>
      <button v-if="store.isAdmin" :disabled="store.loading" class="button-secondary" @click="resetSimulation">リセット</button>
      <span v-if="formattedPosition" class="hud-coordinates">LOC: {{ formattedPosition }}</span>
    </div>

    <section v-if="selectedLog" class="hud-log-float">
      <button class="hud-close" type="button" aria-label="ログを閉じる" @click="selectedLog = null">x</button>
      <p class="muted">{{ logClock(selectedLog) }} / {{ selectedLog.communication_status }} / 信頼度 {{ selectedLog.reliability.toFixed(2) }}</p>
      <h2>{{ selectedLog.title }}</h2>
      <p>{{ selectedLog.summary }}</p>
      <div class="log-body log-body--rendered" v-html="selectedLogBody" />
      <div class="floating-facts">
        <div>
          <h3>観測事実</h3>
          <p v-if="!selectedLog.observations.length" class="muted">新しい観測事実はありません。</p>
          <p v-for="obs in selectedLog.observations" :key="`${obs.type}-${obs.value}`">{{ obs.type }}: {{ obs.value }} ({{ obs.reliability.toFixed(2) }})</p>
        </div>
        <div>
          <h3>解釈</h3>
          <p v-if="!selectedLog.interpretations.length" class="muted">新しい解釈はありません。</p>
          <p v-for="item in selectedLog.interpretations" :key="item.hypothesis">{{ item.hypothesis }} ({{ item.confidence.toFixed(2) }})</p>
        </div>
      </div>
    </section>
  </main>
</template>
