<script setup lang="ts">
const store = useMissionStore()
onMounted(() => store.loadAll())
</script>

<template>
  <main class="page">
    <h1>3D 宇宙マップ</h1>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <ClientOnly>
      <SpaceMap v-if="store.map" :payload="store.map" />
    </ClientOnly>
  </main>
</template>
