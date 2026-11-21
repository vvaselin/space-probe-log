<script setup lang="ts">
const voyage = useVoyageStore()
onMounted(() => {
  void voyage.refreshLogs()
})
</script>

<template>
  <main class="page">
    <h1>探査ログ</h1>
    <div v-if="voyage.error" class="error">{{ voyage.error }}</div>
    <div class="grid">
      <LogCard v-for="log in voyage.logs" :key="log.log_number" :log="log" />
    </div>
    <p v-if="!voyage.logs.length" class="muted">ログはまだ書かれていません。</p>
  </main>
</template>
