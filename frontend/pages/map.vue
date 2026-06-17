<script setup lang="ts">
const store = useMissionStore()
onMounted(() => store.loadAll())

const mapKey = computed(() => {
  const map = store.map
  if (!map) return 'map-loading'
  return [
    'map-page',
    store.sceneRevision,
    map.probe.id,
    map.probe.system_id,
    map.probe.target_id ?? 'idle',
    map.systems.length,
  ].join(':')
})
</script>

<template>
  <main class="page">
    <h1>3D 宇宙マップ</h1>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <ClientOnly>
      <SpaceMap v-if="store.map" :key="mapKey" :payload="store.map" />
    </ClientOnly>
  </main>
</template>
