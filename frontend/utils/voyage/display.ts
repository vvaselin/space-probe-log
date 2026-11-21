// 物理座標（AU）から表示座標への変換。フロントだけが持つ（11章）。バックはこの座標を計算も保存もしない。
//
// - 太陽からの距離は対数で縮める（水星から約90 AUまでを1画面に収める）
// - 天体の周りは、外向きの「押し出し」を足して局所的に広げる（衛星の軌道と、最接近距離にいる探査機が見えるように）
// - 押し出しは距離とともになめらかに増えて、遠くでゆっくり消える。どこでも途切れず、天体から離れるほど表示上も離れる
import { AU_KM, add, norm, scale, sub } from './orbits.ts'
import type { VoyageBody, Vec3 } from './types.ts'

const GLOBAL_SCALE = 40 // 表示単位
const GLOBAL_R0_AU = 0.3
const SYSTEM_PUSH = 2.5 // 衛星を持つ天体の周りの広がり（表示単位）
const BODY_PUSH_PER_RADIUS = 2.5 // 天体自身の周りの広がり（表示上の半径の何倍か）
const BODY_SCALE_RADII = 4 // 天体の半径の何倍で押し出しが半分になるか
const FADE_FRACTION = 0.25 // 太陽からの距離のこの割合より遠くで、押し出しが消えていく

export type Push = { center: Vec3; scaleAu: number; strength: number; fadeAu: number }

/** 表示上の球の半径（表示単位）。実際の比率ではなく、見分けられる大きさにする。 */
export function displayRadius(body: Pick<VoyageBody, 'subtype' | 'radius_km'>): number {
  if (body.subtype === 'star') return 2
  return Math.min(0.9, Math.max(0.12, 0.12 + 0.18 * Math.log10(body.radius_km / 100)))
}

function globalMap(p: Vec3): Vec3 {
  const r = norm(p)
  if (r === 0) return [0, 0, 0]
  return scale(p, (GLOBAL_SCALE * Math.log10(1 + r / GLOBAL_R0_AU)) / r)
}

/** その時刻の天体の位置から、押し出しの一覧を作る（太陽は押し出さない）。 */
export function pushesFor(bodies: VoyageBody[], positions: Map<string, Vec3>): Push[] {
  const pushes: Push[] = []
  for (const body of bodies) {
    const center = positions.get(body.id)
    if (!center || body.subtype === 'star') continue
    const fadeAu = FADE_FRACTION * Math.max(norm(center), 0.1)
    pushes.push({
      center,
      scaleAu: (BODY_SCALE_RADII * body.radius_km) / AU_KM,
      strength: BODY_PUSH_PER_RADIUS * displayRadius(body),
      fadeAu,
    })
    const orbits = bodies
      .filter((child) => child.parent_id === body.id && child.orbit.kind === 'circular')
      .map((child) => (child.orbit.kind === 'circular' ? child.orbit.orbit_radius_km : 0))
    if (orbits.length) pushes.push({ center, scaleAu: Math.max(...orbits) / 3 / AU_KM, strength: SYSTEM_PUSH, fadeAu })
  }
  return pushes
}

export function toDisplay(p: Vec3, pushes: Push[]): Vec3 {
  let out = globalMap(p)
  for (const push of pushes) {
    const offset = sub(p, push.center)
    const d = norm(offset)
    if (d === 0) continue
    const x = d / push.scaleAu
    const amount = (push.strength * (x / (1 + x))) / Math.sqrt(1 + (d / push.fadeAu) ** 2)
    out = add(out, scale(offset, amount / d))
  }
  return out
}

/** 黄道座標（z が北）を three.js の座標（y が上）にする。 */
export const toScene = (v: Vec3): Vec3 => [v[0], v[2], -v[1]]
