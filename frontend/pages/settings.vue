<script setup lang="ts">
const store = useMissionStore()
const presetText = ref('')

onMounted(async () => {
  await store.restoreAdminSession()
  if (!store.isAdmin) {
    await navigateTo('/admin/login')
    return
  }
  await store.loadSimulationSettings()
  presetText.value = (store.simulationSettings?.time_scale_presets ?? []).join(', ')
})

const defaultScale = computed({
  get: () => store.simulationSettings?.default_time_scale ?? 500000,
  set: (value: number) => {
    if (store.simulationSettings) store.simulationSettings.default_time_scale = Number(value)
  }
})

const advanceOffline = computed({
  get: () => store.simulationSettings?.advance_offline ?? true,
  set: (value: boolean) => {
    if (store.simulationSettings) store.simulationSettings.advance_offline = value
  }
})

const maxOfflineHours = computed({
  get: () => Math.round((store.simulationSettings?.max_offline_elapsed_seconds ?? 86400) / 3600),
  set: (value: number) => {
    if (store.simulationSettings) store.simulationSettings.max_offline_elapsed_seconds = Math.max(0, Number(value)) * 3600
  }
})

async function save() {
  const presets = presetText.value
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item >= 0)
  await store.saveSimulationSettings({
    default_time_scale: defaultScale.value,
    advance_offline: advanceOffline.value,
    max_offline_elapsed_seconds: maxOfflineHours.value * 3600,
    time_scale_presets: presets
  })
  await store.refreshClock()
}
</script>

<template>
  <main class="page">
    <h1>Simulation Settings</h1>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <section v-if="store.isAdmin && store.simulationSettings" class="panel form-panel">
      <label>
        Default time scale
        <select v-model.number="defaultScale">
          <option v-for="preset in store.simulationSettings.time_scale_presets" :key="preset" :value="preset">
            {{ preset === 0 ? 'PAUSE' : `x${preset.toLocaleString()}` }}
          </option>
        </select>
      </label>
      <label class="check-row">
        <input v-model="advanceOffline" type="checkbox">
        Advance while offline
      </label>
      <label>
        Max offline elapsed time to apply (hours)
        <input v-model.number="maxOfflineHours" type="number" min="0">
      </label>
      <label>
        Available time scale presets
        <input v-model="presetText" type="text">
      </label>
      <div class="toolbar">
        <button :disabled="store.loading" type="button" @click="save">Save</button>
        <button class="button-secondary" type="button" @click="store.refreshClock">Refresh Clock</button>
      </div>
    </section>
  </main>
</template>
