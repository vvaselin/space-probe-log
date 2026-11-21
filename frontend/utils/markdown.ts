// ログ本文の Markdown を HTML にする（見出し、段落、区切り線、太字、斜体、コードだけ）。HTML はエスケープする。

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

export function renderLogMarkdown(markdown: string): string {
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
    if (/^-{3,}$/.test(line)) {
      flushParagraph()
      blocks.push('<hr>')
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading?.[1] && heading[2]) {
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
