<script setup lang="ts">
// 管理者の時計の操作（10章、12章）。管理者でログインしている時だけ表示する。
const props = defineProps<{ compact?: boolean }>()

const api = useApi()
const mission = useMissionStore()
const voyage = useVoyageStore()
const busy = ref(false)
const message = ref<string | null>(null)
const customInterval = ref<number | null>(null)
const INTERVAL_PRESETS = [
  { label: '24時間', seconds: 86_400 },
  { label: '1時間', seconds: 3_600 },
  { label: '5分', seconds: 300 },
  { label: '1分', seconds: 60 },
]
const clock = computed(() => voyage.sync?.clock ?? null)

async function run(label: string, action: (csrf: string) => Promise<unknown>) {
  const csrf = mission.adminSession?.csrf_token
  if (!csrf) {
    message.value = '管理者ログインが必要です'
    return
  }
  busy.value = true
  try {
    const result = await action(csrf)
    message.value = result && typeof result === 'object' && 'log_number' in result
      ? `LOG #${String(result.log_number).padStart(3, '0')} を書いた`
      : `${label}：完了`
    await voyage.refresh()
  } catch (err) {
    message.value = `${label}：${err instanceof Error ? err.message : String(err)}`
  } finally {
    busy.value = false
  }
}

const changeInterval = (seconds: number) => run('間隔の変更', (csrf) => api.updateVoyageClock({ interval_seconds: seconds }, csrf))
</script>

<template>
  <section v-if="mission.isAdmin && clock" class="voyage-admin" :class="{ 'voyage-admin--compact': props.compact }">
    <span>公開 {{ clock.mode === 'auto' ? '自動' : '手動' }}・間隔 {{ clock.interval_seconds.toLocaleString('ja-JP') }} 秒</span>
    <button type="button" :disabled="busy || clock.ended" @click="run('次の場面へ進める', api.stepVoyage)">次の場面へ進める</button>
    <button v-if="clock.paused" type="button" :disabled="busy" @click="run('再開', api.resumeVoyage)">再開</button>
    <button v-else type="button" :disabled="busy" @click="run('一時停止', api.pauseVoyage)">一時停止</button>
    <button
      type="button"
      :disabled="busy"
      @click="run('モードの切り替え', (csrf) => api.updateVoyageClock({ mode: clock?.mode === 'auto' ? 'manual' : 'auto' }, csrf))"
    >
      {{ clock.mode === 'auto' ? '手動にする' : '自動にする' }}
    </button>
    <span v-if="!props.compact" class="voyage-admin__intervals">
      間隔:
      <button v-for="preset in INTERVAL_PRESETS" :key="preset.seconds" type="button" :disabled="busy" @click="changeInterval(preset.seconds)">
        {{ preset.label }}
      </button>
      <input v-model.number="customInterval" type="number" min="1" placeholder="秒" />
      <button type="button" :disabled="busy || !customInterval || customInterval < 1" @click="changeInterval(customInterval ?? 0)">設定</button>
    </span>
    <span v-if="message">{{ message }}</span>
  </section>
</template>

<style scoped>
.voyage-admin {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin: 12px 0;
  font-size: 13px;
}
.voyage-admin--compact {
  margin: 0;
}
.voyage-admin__intervals input {
  width: 7em;
}
</style>
