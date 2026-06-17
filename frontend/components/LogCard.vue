<script setup lang="ts">
import type { LogListItem } from '~/types/api'

defineProps<{ log: LogListItem }>()

function logClock(log: LogListItem) {
  const clock = log.probe_position?.mission_clock
  return typeof clock === 'string' ? clock : new Date(log.generated_at).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}
</script>

<template>
  <NuxtLink class="card" :to="`/logs/${log.id}`" style="display: block;">
    <p class="muted">{{ logClock(log) }} | {{ log.log_type }} | 信頼度 {{ log.reliability.toFixed(2) }}</p>
    <h2>{{ log.title }}</h2>
    <p>{{ log.summary }}</p>
  </NuxtLink>
</template>
