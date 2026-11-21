<script setup lang="ts">
import type { VoyageLogItem } from '~/utils/voyage/types'

defineProps<{ log: VoyageLogItem }>()
</script>

<template>
  <NuxtLink class="card" :to="`/logs/${log.log_number}`" style="display: block;">
    <p class="muted">
      LOG #{{ String(log.log_number).padStart(3, '0') }} | {{ log.sim_time }} | {{ log.scene }}（{{ log.subject }}）
      <template v-if="log.revision > 1"> | 第{{ log.revision }}版</template>
      <template v-if="log.fallback"> | 定型文</template>
    </p>
    <h2>{{ log.title }}</h2>
    <p>{{ log.summary }}</p>
  </NuxtLink>
</template>
