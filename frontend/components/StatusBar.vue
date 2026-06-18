<script setup lang="ts">
defineProps<{ label: string; value: number; max?: number }>()
</script>

<template>
  <div class="status-meter">
    <div class="status-meter__head">
      <span>{{ label }}</span>
      <span>{{ value.toFixed(1) }} / {{ (max ?? 100).toFixed(0) }}</span>
    </div>
    <div class="status-meter__track">
      <div class="status-meter__fill" :style="{ width: `${Math.max(0, Math.min(100, value / (max ?? 100) * 100))}%` }" />
    </div>
  </div>
</template>
