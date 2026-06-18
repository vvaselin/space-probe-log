<script setup lang="ts">
const store = useMissionStore()
let clockTimer: number | null = null

onMounted(async () => {
  await Promise.allSettled([store.refreshClock(), store.loadSimulationSettings(), store.restoreAdminSession()])
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

async function logout() {
  await store.logoutAdmin()
  await navigateTo('/')
}
</script>

<template>
  <div class="shell">
    <nav class="nav">
      <div class="nav__primary">
        <NuxtLink class="brand" to="/">INSOMNIA-07</NuxtLink>
        <div class="nav__links">
          <NuxtLink to="/logs">Logs</NuxtLink>
          <NuxtLink to="/map">Map</NuxtLink>
          <NuxtLink to="/probe">Probe</NuxtLink>
          <NuxtLink v-if="store.isAdmin" to="/settings">Settings</NuxtLink>
          <NuxtLink v-else to="/admin/login">Admin</NuxtLink>
          <button v-if="store.isAdmin" class="nav__logout" type="button" @click="logout">Logout</button>
        </div>
      </div>
      <div class="sim-hud" :class="{ 'sim-hud--paused': store.clock?.clock_state === 'paused' }">
        <span class="sim-hud__clock">SIM TIME {{ store.clock?.mission_clock ?? '2080/05/02 12:00:00 UTC' }}</span>
        <label>
          TIME
          <select v-if="store.isAdmin" v-model.number="selectedScale">
            <option v-for="preset in presets" :key="preset" :value="preset">
              {{ `x${preset.toLocaleString()}` }}
            </option>
          </select>
          <span v-else class="sim-hud__scale">{{ `x${selectedScale.toLocaleString()}` }}</span>
        </label>
        <strong class="sim-hud__state">{{ store.clock?.clock_state === 'paused' ? 'PAUSED' : 'RUNNING' }}</strong>
      </div>
    </nav>
    <NuxtPage />
  </div>
</template>
