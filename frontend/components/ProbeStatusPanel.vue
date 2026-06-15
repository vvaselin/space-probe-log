<script setup lang="ts">
import type { Probe } from '~/types/api'

defineProps<{ probe: Probe }>()
</script>

<template>
  <section class="panel probe-status">
    <div class="probe-status__head">
      <div>
        <p class="muted">探査機</p>
        <h2>{{ probe.name }}</h2>
        <p>{{ probe.current_system_id }} / T+{{ probe.mission_time }}</p>
      </div>
      <div class="probe-status__mission">{{ probe.current_mission }}</div>
    </div>
    <div class="status-grid">
      <StatusBar label="エネルギー" :value="probe.energy" />
      <StatusBar label="燃料" :value="probe.fuel" />
      <StatusBar label="船体" :value="probe.hull" />
      <StatusBar label="通信" :value="probe.communication" />
      <StatusBar label="センサー" :value="probe.sensors" />
      <StatusBar label="推進系" :value="probe.propulsion" />
      <StatusBar label="ストレージ" :value="probe.storage_used" :max="probe.storage_capacity" />
    </div>
  </section>
</template>
