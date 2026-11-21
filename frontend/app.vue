<script setup lang="ts">
const store = useMissionStore()
const voyage = useVoyageStore()
const hud = useVoyageHud()

onMounted(() => {
  voyage.start()
  void store.restoreAdminSession()
})

onBeforeUnmount(() => voyage.stop())

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
          <NuxtLink v-if="!store.isAdmin" to="/admin/login">Admin</NuxtLink>
          <button v-if="store.isAdmin" class="nav__logout" type="button" @click="logout">Logout</button>
        </div>
      </div>
      <div class="sim-hud" :class="{ 'sim-hud--paused': hud.paused }">
        <span class="sim-hud__clock">SIM TIME {{ hud.sim }}</span>
        <label>公開 <span class="sim-hud__scale">{{ hud.mode }}</span></label>
        <strong class="sim-hud__state">{{ hud.paused ? 'PAUSED' : 'RUNNING' }}</strong>
      </div>
    </nav>
    <NuxtPage />
  </div>
</template>
