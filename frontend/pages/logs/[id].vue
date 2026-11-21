<script setup lang="ts">
// ログの詳細。URL の数字はログ番号（書き直しても同じURLで、最新の版を表示する）。
import type { VoyageLogDetail } from '~/utils/voyage/types'

const route = useRoute()
const api = useApi()
const log = ref<VoyageLogDetail | null>(null)
const error = ref<string | null>(null)
const renderedBody = computed(() => renderLogMarkdown(log.value?.body_markdown ?? ''))

onMounted(async () => {
  try {
    log.value = await api.getVoyageLog(String(route.params.id))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'API error'
  }
})
</script>

<template>
  <main class="page">
    <div v-if="error" class="error">{{ error }}</div>
    <article v-if="log" class="log-detail-layout">
      <section class="panel log-detail-main">
        <p class="muted">
          {{ log.sim_time }} / {{ log.scene }}（{{ log.subject }}） / 公開 {{ new Date(log.published_at).toISOString().slice(0, 16).replace('T', ' ') }} UTC
        </p>
        <div class="log-body log-body--rendered" v-html="renderedBody" />
      </section>
      <aside class="panel log-detail-aside">
        <section>
          <h2>場面と位置</h2>
          <p>{{ log.scene }}（{{ log.subject }}） / {{ log.sim_time }}</p>
          <p>太陽から {{ log.position.sun_distance_au }} AU / 地球から {{ log.position.earth_distance_km.toLocaleString('ja-JP') }} km</p>
          <p>速度 毎秒 {{ log.speed.km_s.toLocaleString('ja-JP') }} km<template v-if="log.speed.state">（{{ log.speed.state }}）</template></p>
          <p>
            {{ log.current_leg.kind }}：{{ log.current_leg.from }} → {{ log.current_leg.to }}
            / 残り {{ log.current_leg.remaining_time }}
          </p>
        </section>
        <section>
          <h2>見えていた天体</h2>
          <p v-for="seen in log.visible" :key="seen.name">
            <strong>{{ seen.name }}</strong>：{{ seen.direction }}、{{ seen.size }}、{{ seen.brightness }}
            <small class="muted">（広角 {{ seen.stage }} / 望遠 {{ seen.telescope_stage }}）</small>
          </p>
        </section>
        <section>
          <h2>次の行き先</h2>
          <template v-if="log.next_destination">
            <p><strong>{{ log.next_destination.name }}</strong>（到着予定 {{ log.next_destination.eta_utc }}）</p>
            <p>{{ log.next_destination.reason }}</p>
          </template>
          <p v-else class="muted">航路の候補がない</p>
        </section>
        <section>
          <h2>記録</h2>
          <p>LOG #{{ String(log.log_number).padStart(3, '0') }} / 第{{ log.revision }}版 / モデル {{ log.model ?? '-' }}</p>
          <p v-if="log.fallback" class="muted">本文の生成に失敗したため、定型文で埋めた</p>
        </section>
      </aside>
    </article>
  </main>
</template>
