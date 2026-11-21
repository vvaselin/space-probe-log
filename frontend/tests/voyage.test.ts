// 実行: npm test（node --test --experimental-strip-types）
// 答えは backend で `python -m app.voyage.golden` が書き出した golden/voyage.json。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { displayRadius, pushesFor, toDisplay } from '../utils/voyage/display.ts'
import { probePosition } from '../utils/voyage/motion.ts'
import { AU_KM, bodyPosition, norm, sub } from '../utils/voyage/orbits.ts'
import { monotoneCubic } from '../utils/voyage/timetable.ts'
import type { LegFormula, Vec3, VoyageBody } from '../utils/voyage/types.ts'

type Golden = {
  bodies: VoyageBody[]
  body_positions: { id: string; at: string; position_au: Vec3 }[]
  start_position_au: Vec3
  legs: LegFormula[]
  leg_samples: { sim_at: string; position_au: Vec3; leg_index: number | null }[]
  timetable: { points: [number, number][]; samples: [number, number][] }
}

const golden = JSON.parse(readFileSync(new URL('./golden/voyage.json', import.meta.url), 'utf-8')) as Golden
const bodies = new Map(golden.bodies.map((b) => [b.id, b]))
const km = (a: Vec3, b: Vec3) => norm(sub(a, b)) * AU_KM

test('天体の位置が Python と同じ（1 km 以内）', () => {
  for (const sample of golden.body_positions) {
    const position = bodyPosition(bodies, bodies.get(sample.id)!, Date.parse(sample.at))
    assert.ok(km(position, sample.position_au) < 1, `${sample.id} @ ${sample.at}: ${km(position, sample.position_au)} km`)
  }
})

test('区間の式による探査機の位置が Python と同じ（1 km 以内）', () => {
  for (const sample of golden.leg_samples) {
    const t = Date.parse(sample.sim_at)
    const { position, leg } = probePosition(golden.legs, golden.start_position_au, t)
    assert.ok(km(position, sample.position_au) < 1, `${sample.sim_at}: ${km(position, sample.position_au)} km`)
    // 区間の境目では、ミリ秒とマイクロ秒の違いで番号が1つずれうる（位置は同じ）
    const atBoundary = golden.legs.some((l) => Math.abs(Date.parse(l.profile.depart_at) - t) < 2)
    if (!atBoundary) assert.equal(leg?.index ?? null, sample.leg_index)
  }
})

test('時刻表の補間が Python と同じ', () => {
  for (const [x, y] of golden.timetable.samples) {
    assert.ok(Math.abs(monotoneCubic(golden.timetable.points, x) - y) < 1e-9, `x=${x}`)
  }
})

function displayAt(simMs: number, p: Vec3): Vec3 {
  const positions = new Map(golden.bodies.map((b) => [b.id, bodyPosition(bodies, b, simMs)]))
  return toDisplay(p, pushesFor(golden.bodies, positions))
}

test('表示座標は区間の上でなめらかにつながる（途中で飛ばない）', () => {
  for (const leg of golden.legs) {
    const start = Date.parse(leg.profile.depart_at)
    const duration = (leg.profile.accel_s + leg.profile.cruise_s + leg.profile.decel_s) * 1000
    let previous: Vec3 | null = null
    const steps: number[] = []
    for (let i = 0; i <= 400; i++) {
      const t = start + (duration * i) / 400
      const shown = displayAt(t, probePosition(golden.legs, golden.start_position_au, t).position)
      if (previous) steps.push(norm(sub(shown, previous)))
      previous = shown
    }
    const total = steps.reduce((a, b) => a + b, 0)
    // 1ステップで、その区間の表示上の道のりの1/4より大きく動いたら「飛んだ」とみなす
    assert.ok(Math.max(...steps) < Math.max(total / 4, 1e-6), `leg ${leg.index}: max step ${Math.max(...steps)} of ${total}`)
  }
})

test('天体から離れるほど、表示上も離れる', () => {
  const t = Date.parse('2080-05-24T12:00:00Z')
  for (const id of ['earth', 'jupiter', 'saturn', 'io', 'pluto']) {
    const body = bodies.get(id)!
    const center = bodyPosition(bodies, body, t)
    const shownCenter = displayAt(t, center)
    let last = 0
    for (let k = 0; k <= 60; k++) {
      const d = ((body.radius_km * 1.05) / AU_KM) * 10 ** (k / 10) // 半径の1.05倍から10^6倍まで
      const shown = norm(sub(displayAt(t, [center[0] + d, center[1] + d * 0.3, center[2]]), shownCenter))
      assert.ok(shown >= last - 1e-9, `${id}: d=${d} AU shown=${shown} < ${last}`)
      last = shown
    }
  }
})

test('最接近距離にいる探査機は、表示上の天体の球の外にいる', () => {
  for (const leg of golden.legs) {
    const arrive = Date.parse(leg.profile.depart_at) + (leg.profile.accel_s + leg.profile.cruise_s + leg.profile.decel_s) * 1000
    const target = bodies.get(leg.target_id)!
    const shownProbe = displayAt(arrive, leg.profile.destination_au)
    const shownTarget = displayAt(arrive, bodyPosition(bodies, target, arrive))
    assert.ok(norm(sub(shownProbe, shownTarget)) > displayRadius(target), `leg ${leg.index} → ${leg.target_id}`)
  }
})
