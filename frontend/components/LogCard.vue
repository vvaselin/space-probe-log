<script setup lang="ts">
import type { LogListItem } from '~/types/api'

defineProps<{ log: LogListItem }>()
</script>

<template>
  <NuxtLink class="card" :to="`/logs/${log.id}`" style="display: block;">
    <p class="muted">T+{{ log.mission_time }} | {{ log.log_type }} | 信頼度 {{ log.reliability.toFixed(2) }}</p>
    <h2>{{ log.title }}</h2>
    <p>{{ log.summary }}</p>
  </NuxtLink>
</template>
