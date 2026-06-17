<script setup lang="ts">
const store = useMissionStore()
onMounted(() => {
  void store.refreshLogs()
})
</script>

<template>
  <main class="page">
    <h1>探査ログ</h1>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <div class="grid">
      <LogCard v-for="log in store.logs" :key="log.id" :log="log" />
    </div>
    <p v-if="!store.logs.length && !store.loading" class="muted">ログはまだ生成されていません。</p>
  </main>
</template>
