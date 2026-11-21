<script setup lang="ts">
// ダッシュボード。地図、今の航行の様子、最新のログ（app/voyage）。
import type { VoyageLogDetail, VoyageLogItem } from '~/utils/voyage/types'

const api = useApi()
const voyage = useVoyageStore()
const hud = useVoyageHud()
const selectedLog = ref<VoyageLogDetail | null>(null)
const logError = ref<string | null>(null)
const latestLogNumber = computed(() => voyage.logs[0]?.log_number ?? null)
const selectedLogBody = computed(() => renderLogMarkdown(selectedLog.value?.body_markdown ?? ''))

onMounted(() => {
  void voyage.refreshLogs()
})

async function openLog(log: VoyageLogItem) {
  logError.value = null
  try {
    selectedLog.value = await api.getVoyageLog(log.log_number)
  } catch (err) {
    logError.value = err instanceof Error ? err.message : 'ログを読み込めませんでした'
  }
}
</script>

<template>
  <main class="dashboard-hud">
    <div class="dashboard-map">
      <ClientOnly>
        <VoyageMap v-if="voyage.sync" :sync="voyage.sync" :now="voyage.now" />
      </ClientOnly>
      <div v-if="!voyage.sync && !voyage.error" class="hud-loading">マップを同期中...</div>
    </div>

    <div v-if="voyage.error" class="hud-error">{{ voyage.error }}</div>

    <aside v-if="hud.ready" class="hud-panel hud-panel--left">
      <section class="hud-identity">
        <p class="hud-kicker">探査機 / 搭載AI NOCTUA-7</p>
        <h1>INSOMNIA-07</h1>
        <p class="hud-location">{{ hud.sim }}</p>
        <div class="hud-position">
          <strong>太陽から {{ hud.sunAu }}</strong>
          <small>地球から {{ hud.earthKm }}</small>
        </div>
      </section>

      <div class="hud-route">
        <span>→ {{ hud.target }}</span>
        <strong>{{ hud.state }}</strong>
        <small>速度 {{ hud.speed }}</small>
        <small>到着まで {{ hud.remaining }}</small>
        <div class="hud-route-bar">
          <span :style="{ width: `${Math.round(hud.progress * 100)}%` }" />
        </div>
      </div>
      <p class="hud-last-event">次の場面: {{ hud.next }}（{{ hud.mode }}）</p>
    </aside>

    <aside class="hud-panel hud-panel--right">
      <div class="hud-panel-head">
        <h2><span>NAV</span> LOG</h2>
        <NuxtLink to="/logs" class="hud-link">一覧</NuxtLink>
      </div>
      <p v-if="logError" class="error">{{ logError }}</p>
      <button
        v-for="log in voyage.logs.slice(0, 6)"
        :key="log.log_number"
        type="button"
        class="hud-log-item"
        :class="{ 'hud-log-item--new': log.log_number === latestLogNumber }"
        @click="openLog(log)"
      >
        <span>LOG #{{ String(log.log_number).padStart(3, '0') }} / {{ log.sim_time }} / {{ log.scene }}</span>
        <strong>{{ log.title }}</strong>
        <small>{{ log.summary }}</small>
      </button>
      <p v-if="!voyage.logs.length" class="muted">ログはまだ書かれていません。</p>
    </aside>

    <div class="hud-controls">
      <VoyageAdminPanel compact />
    </div>

    <section v-if="selectedLog" class="hud-log-float">
      <button class="hud-close" type="button" aria-label="ログを閉じる" @click="selectedLog = null">x</button>
      <p class="muted">{{ selectedLog.sim_time }} / {{ selectedLog.scene }}（{{ selectedLog.subject }}）</p>
      <div class="log-body log-body--rendered" v-html="selectedLogBody" />
      <p>
        <NuxtLink :to="`/logs/${selectedLog.log_number}`">詳しく見る</NuxtLink>
      </p>
    </section>
  </main>
</template>
