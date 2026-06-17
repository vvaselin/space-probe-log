<script setup lang="ts">
const store = useMissionStore()
let clockTimer: number | null = null

onMounted(async () => {
  await Promise.allSettled([store.refreshClock(), store.loadSimulationSettings()])
  clockTimer = window.setInterval(() => {
    void store.refreshClock()
  }, 5000)
})

onBeforeUnmount(() => {
  if (clockTimer !== null) window.clearInterval(clockTimer)
})

const presets = computed(() => (store.simulationSettings?.time_scale_presets ?? [1, 10000, 100000, 500000]).filter((preset) => preset > 0))
const selectedScale = computed({
  get: () => {
    const currentScale = store.clock?.time_scale ?? 0
    return currentScale > 0 ? currentScale : presets.value[0] ?? 500000
  },
  set: (value: number) => {
    void store.setTimeScale(Number(value))
  }
})
</script>

<template>
  <div class="shell">
    <nav class="nav">
      <NuxtLink class="brand" to="/">INSOMNIA-07</NuxtLink>
      <NuxtLink to="/logs">Logs</NuxtLink>
      <NuxtLink to="/map">Map</NuxtLink>
      <NuxtLink to="/probe">Probe</NuxtLink>
      <NuxtLink to="/settings">Settings</NuxtLink>
      <div class="sim-hud" :class="{ 'sim-hud--paused': store.clock?.clock_state === 'paused' }">
        <span>SIM TIME {{ store.clock?.mission_clock ?? '2080/05/02 12:00:00 UTC' }}</span>
        <label>
          TIME
          <select v-model.number="selectedScale">
            <option v-for="preset in presets" :key="preset" :value="preset">
              {{ `x${preset.toLocaleString()}` }}
            </option>
          </select>
        </label>
        <strong>{{ store.clock?.clock_state === 'paused' ? 'PAUSED' : 'RUNNING' }}</strong>
      </div>
    </nav>
    <NuxtPage />
  </div>
</template>
