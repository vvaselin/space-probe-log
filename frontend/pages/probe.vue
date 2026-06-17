<script setup lang="ts">
const store = useMissionStore()
onMounted(() => store.loadAll())
</script>

<template>
  <main class="page">
    <h1>探査機状態</h1>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <div v-if="store.probe" class="grid">
      <section class="panel"><StatusBar label="船体" :value="store.probe.hull" /></section>
      <section class="panel"><StatusBar label="通信" :value="store.probe.communication" /></section>
      <section class="panel"><StatusBar label="センサー" :value="store.probe.sensors" /></section>
      <section class="panel"><StatusBar label="推進系" :value="store.probe.propulsion" /></section>
      <section class="panel"><StatusBar label="エネルギー" :value="store.probe.energy" /></section>
      <section class="panel"><StatusBar label="ストレージ" :value="store.probe.storage_used" :max="store.probe.storage_capacity" /></section>
      <section class="panel">
        <h2>資源</h2>
        <p v-for="(quantity, name) in store.probe.collected_resources" :key="name">{{ name }}: {{ quantity }}</p>
        <p v-if="!Object.keys(store.probe.collected_resources).length" class="muted">未取得</p>
      </section>
      <section class="panel">
        <h2>発見数</h2>
        <p>天体 {{ store.probe.discovered_body_ids.length }}</p>
        <p>星系 {{ store.systems.length }}</p>
      </section>
    </div>
  </main>
</template>
