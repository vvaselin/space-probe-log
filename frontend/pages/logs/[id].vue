<script setup lang="ts">
import type { LogDetail } from '~/types/api'

const route = useRoute()
const api = useApi()
const log = ref<LogDetail | null>(null)
const error = ref<string | null>(null)

const snapshot = computed<Record<string, unknown>>(() => log.value?.probe_state_snapshot ?? {})
const discoveries = computed(() => {
  const value = snapshot.value.discovered_body_ids
  return Array.isArray(value) ? value.map(String) : []
})
const resources = computed(() => {
  const value = snapshot.value.collected_resources
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, number> : {}
})
const renderedBody = computed(() => renderMarkdown(log.value?.body_markdown ?? ''))

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`\s*([^`]+?)\s*`/g, '<code>$1</code>')
}

function renderMarkdown(markdown: string) {
  const blocks: string[] = []
  let paragraph: string[] = []
  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join('<br>')}</p>`)
    paragraph = []
  }

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trimEnd()
    if (!line.trim()) {
      flushParagraph()
      continue
    }
    if (line === '---' || line === '---------------------') {
      flushParagraph()
      blocks.push('<hr>')
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushParagraph()
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    paragraph.push(line)
  }

  flushParagraph()
  return blocks.join('\n')
}

function numberValue(key: string) {
  const value = snapshot.value[key]
  return typeof value === 'number' ? value : 0
}

function textValue(key: string, fallback = '-') {
  const value = snapshot.value[key]
  return typeof value === 'string' ? value : fallback
}

onMounted(async () => {
  try {
    log.value = await api.getLog(String(route.params.id))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'API error'
  }
})
</script>

<template>
  <main class="page">
    <div v-if="error" class="error">{{ error }}</div>
    <article v-if="log" class="log-detail-layout">
      <section class="panel log-detail-main">
        <p class="muted">T+{{ log.mission_time }} / {{ log.communication_status }} / 信頼度 {{ log.reliability.toFixed(2) }}</p>
        <h1>{{ log.title }}</h1>
        <p>{{ log.summary }}</p>
        <div class="log-body log-body--rendered" v-html="renderedBody" />
      </section>

      <aside class="panel log-detail-aside">
        <section>
          <h2>観測事実</h2>
          <p v-if="!log.observations.length" class="muted">新しい観測事実はありません。</p>
          <p v-for="obs in log.observations" :key="`${obs.type}-${obs.value}`">{{ obs.type }}: {{ obs.value }} ({{ obs.reliability.toFixed(2) }})</p>
        </section>

        <section>
          <h2>解釈</h2>
          <p v-if="!log.interpretations.length" class="muted">新しい解釈はありません。</p>
          <p v-for="item in log.interpretations" :key="item.hypothesis">{{ item.hypothesis }} ({{ item.confidence.toFixed(2) }})</p>
        </section>

        <section>
          <h2>状態スナップショット</h2>
          <div class="snapshot-meta">
            <span>現在地: {{ textValue('current_system_id') }}</span>
            <span>時刻: T+{{ numberValue('mission_time') }}</span>
          </div>
          <div class="snapshot-bars">
            <StatusBar label="エネルギー" :value="numberValue('energy')" />
            <StatusBar label="船体" :value="numberValue('hull')" />
            <StatusBar label="通信" :value="numberValue('communication')" />
            <StatusBar label="センサー" :value="numberValue('sensors')" />
            <StatusBar label="推進系" :value="numberValue('propulsion')" />
            <StatusBar label="ストレージ" :value="numberValue('storage_used')" :max="numberValue('storage_capacity') || 100" />
          </div>
        </section>

        <section>
          <h2>発見と資源</h2>
          <p>発見済み天体: {{ discoveries.length ? discoveries.join(', ') : 'なし' }}</p>
          <p>取得資源: {{ Object.keys(resources).length ? JSON.stringify(resources) : 'なし' }}</p>
        </section>

        <details class="snapshot-raw">
          <summary>詳細JSONを表示</summary>
          <pre>{{ JSON.stringify(log.probe_state_snapshot, null, 2) }}</pre>
        </details>
      </aside>
    </article>
  </main>
</template>
