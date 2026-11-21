// backend/app/voyage/sync.py の monotone_cubic と sim_time_at と同じ式。変えたら両方を直す。
import { isoToMs } from './orbits.ts'
import type { TimetablePoint } from './types.ts'

/** 単調3次補間（Fritsch–Carlson）。点を必ず通り、行き過ぎない。範囲の外は端の値で止まる。 */
export function monotoneCubic(points: [number, number][], x: number): number {
  if (points.length === 0) throw new Error('timetable has no points')
  const xs = points.map((p) => p[0])
  const ys = points.map((p) => p[1])
  const n = points.length
  if (x <= xs[0]!) return ys[0]!
  if (x >= xs[n - 1]!) return ys[n - 1]!
  const h = xs.slice(0, -1).map((v, i) => xs[i + 1]! - v)
  const d = h.map((hi, i) => (ys[i + 1]! - ys[i]!) / hi)
  const m = new Array<number>(n).fill(0)
  m[0] = d[0]!
  m[n - 1] = d[n - 2]!
  for (let i = 1; i < n - 1; i++) {
    const [d0, d1, h0, h1] = [d[i - 1]!, d[i]!, h[i - 1]!, h[i]!]
    if (d0 * d1 <= 0) continue
    const w1 = 2 * h1 + h0
    const w2 = h1 + 2 * h0
    m[i] = (w1 + w2) / (w1 / d0 + w2 / d1)
  }
  let i = 0
  while (i < n - 2 && xs[i + 1]! <= x) i++
  const hi = h[i]!
  const t = (x - xs[i]!) / hi
  const t2 = t * t
  const t3 = t2 * t
  return (2 * t3 - 3 * t2 + 1) * ys[i]! + (t3 - 2 * t2 + t) * hi * m[i]! + (-2 * t3 + 3 * t2) * ys[i + 1]! + (t3 - t2) * hi * m[i + 1]!
}

/** 現実の時刻（UNIXミリ秒）から、シミュレーション内の時刻（UNIXミリ秒）。 */
export function simTimeAt(timetable: TimetablePoint[], realMs: number): number {
  const points: [number, number][] = []
  for (const p of timetable) {
    const x = isoToMs(p.real_at)
    const y = isoToMs(p.sim_at)
    const last = points.at(-1)
    if (last && x <= last[0]) {
      points[points.length - 1] = [x, y] // 同じ時刻の点は後の物を使う
      continue
    }
    points.push([x, y])
  }
  return monotoneCubic(points, realMs)
}
