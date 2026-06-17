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

const presets = computed(() => store.simulationSettings?.time_scale_presets ?? [0, 360, 1440, 10080, 525600])
const selectedScale = computed({
  get: () => store.clock?.time_scale ?? 360,
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
              {{ preset === 0 ? 'PAUSE' : `x${preset.toLocaleString()}` }}
            </option>
          </select>
        </label>
        <strong>{{ store.clock?.clock_state === 'paused' ? 'PAUSED' : 'RUNNING' }}</strong>
        <button
          type="button"
          class="sim-hud__button"
          @click="store.setClockState(store.clock?.clock_state === 'paused' ? 'running' : 'paused')"
        >
          {{ store.clock?.clock_state === 'paused' ? 'Resume' : 'Pause' }}
        </button>
      </div>
    </nav>
    <NuxtPage />
  </div>
</template>
