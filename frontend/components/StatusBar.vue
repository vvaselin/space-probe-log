<script setup lang="ts">
defineProps<{ label: string; value: number; max?: number }>()
</script>

<template>
  <div>
    <div class="toolbar" style="justify-content: space-between; margin: 0 0 6px;">
      <span>{{ label }}</span>
      <span class="muted">{{ value.toFixed(1) }} / {{ (max ?? 100).toFixed(0) }}</span>
    </div>
    <div style="height: 8px; border-radius: 6px; background: #253044; overflow: hidden;">
      <div :style="{ width: `${Math.max(0, Math.min(100, value / (max ?? 100) * 100))}%` }" style="height: 100%; background: #71d6a5;" />
    </div>
  </div>
</template>
