<script setup lang="ts">
import type { LogDetail, LogListItem } from '~/types/api'

const store = useMissionStore()
const api = useApi()
const selectedLog = ref<LogDetail | null>(null)
const logError = ref<string | null>(null)
const followTick = ref(0)

onMounted(() => store.loadAll())

const mapKey = computed(() => {
  const probe = store.map?.probe
  return probe ? `${probe.system_id}-${probe.x}-${probe.y}-${probe.z}-${probe.target_id ?? 'idle'}` : 'map-loading'
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
</script>

<template>
  <main class="dashboard-hud">
    <div class="dashboard-map">
      <ClientOnly>
        <SpaceMap
          v-if="store.map"
          :key="mapKey"
          :payload="store.map"
          :follow-tick="followTick"
          hide-toolbar
        />
      </ClientOnly>
      <div v-if="!store.map && !store.error" class="hud-loading">マップを同期中...</div>
    </div>

    <div v-if="store.error" class="hud-error">{{ store.error }}</div>

    <aside v-if="store.probe" class="hud-panel hud-panel--left">
      <p class="hud-kicker">探査機</p>
      <h1>{{ store.probe.name }}</h1>
      <p class="hud-location">{{ store.probe.current_system_id }} / T+{{ store.probe.mission_time }}</p>
      <p v-if="store.probe.target_id" class="hud-target">航行中: {{ store.probe.target_id }}</p>
      <p class="hud-mission">{{ store.probe.current_mission }}</p>
      <div class="hud-status-list">
        <StatusBar label="エネルギー" :value="store.probe.energy" />
        <StatusBar label="燃料" :value="store.probe.fuel" />
        <StatusBar label="船体" :value="store.probe.hull" />
        <StatusBar label="通信" :value="store.probe.communication" />
        <StatusBar label="センサー" :value="store.probe.sensors" />
        <StatusBar label="推進系" :value="store.probe.propulsion" />
        <StatusBar label="ストレージ" :value="store.probe.storage_used" :max="store.probe.storage_capacity" />
      </div>
    </aside>

    <aside class="hud-panel hud-panel--right">
      <div class="hud-panel-head">
        <h2>航行ログ</h2>
        <NuxtLink to="/logs" class="hud-link">一覧</NuxtLink>
      </div>
      <p v-if="logError" class="error">{{ logError }}</p>
      <button
        v-for="log in store.logs.slice(0, 6)"
        :key="log.id"
        type="button"
        class="hud-log-item"
        @click="openLog(log)"
      >
        <span>T+{{ log.mission_time }} / 信頼度 {{ log.reliability.toFixed(2) }}</span>
        <strong>{{ log.title }}</strong>
        <small>{{ log.summary }}</small>
      </button>
      <p v-if="!store.logs.length && !store.loading" class="muted">ログはまだ生成されていません。</p>
    </aside>

    <div class="hud-controls">
      <button :disabled="store.loading" @click="store.runStep">次の探査を実行</button>
      <button class="button-secondary" type="button" @click="followTick++">探査機を追尾</button>
      <button :disabled="store.loading" class="button-secondary" @click="resetSimulation">リセット</button>
    </div>

    <section v-if="selectedLog" class="hud-log-float">
      <button class="hud-close" type="button" aria-label="ログを閉じる" @click="selectedLog = null">×</button>
      <p class="muted">T+{{ selectedLog.mission_time }} / {{ selectedLog.communication_status }} / 信頼度 {{ selectedLog.reliability.toFixed(2) }}</p>
      <h2>{{ selectedLog.title }}</h2>
      <p>{{ selectedLog.summary }}</p>
      <div class="log-body">{{ selectedLog.body_markdown }}</div>
      <div class="floating-facts">
        <div>
          <h3>観測事実</h3>
          <p v-if="!selectedLog.observations.length" class="muted">新規の観測事実はありません。</p>
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
