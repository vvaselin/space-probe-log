// backend/app/voyage/orbits.py と world.py の position_au と同じ式。変えたら両方を直す。
import type { VoyageBody, Vec3 } from './types.ts'

export const AU_KM = 149_597_870.7
export const DAY_MS = 86_400_000
const J2000_MS = Date.UTC(2000, 0, 1, 12)
const DEG = Math.PI / 180

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k]
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
export const norm = (a: Vec3): number => Math.sqrt(dot(a, a))

/** ISO 形式の時刻を UNIX ミリ秒にする。Date.parse が切り捨てるミリ秒未満（Python のマイクロ秒）も足す。 */
export function isoToMs(iso: string): number {
  const base = Date.parse(iso)
  const fraction = /\.\d{3}(\d+)/.exec(iso)?.[1]
  return fraction ? base + Number(`0.${fraction}`) : base
}

// Python の % と同じく、常に 0 以上を返す
const mod = (x: number, m: number): number => ((x % m) + m) % m

export function solveKepler(meanAnomalyRad: number, e: number): number {
  let ecc = e > 0.8 ? Math.PI : meanAnomalyRad
  for (let k = 0; k < 50; k++) {
    const delta = (ecc - e * Math.sin(ecc) - meanAnomalyRad) / (1 - e * Math.cos(ecc))
    ecc -= delta
    if (Math.abs(delta) < 1e-12) return ecc
  }
  throw new Error(`Kepler equation did not converge (M=${meanAnomalyRad}, e=${e})`)
}

export function keplerPosition(a: number, e: number, iDeg: number, nodeDeg: number, periDeg: number, meanAnomalyDeg: number): Vec3 {
  const ecc = solveKepler((mod(meanAnomalyDeg + 180, 360) - 180) * DEG, e)
  const xp = a * (Math.cos(ecc) - e)
  const yp = a * Math.sqrt(1 - e * e) * Math.sin(ecc)
  const [cw, sw] = [Math.cos(periDeg * DEG), Math.sin(periDeg * DEG)]
  const [co, so] = [Math.cos(nodeDeg * DEG), Math.sin(nodeDeg * DEG)]
  const [ci, si] = [Math.cos(iDeg * DEG), Math.sin(iDeg * DEG)]
  return [
    (cw * co - sw * so * ci) * xp + (-sw * co - cw * so * ci) * yp,
    (cw * so + sw * co * ci) * xp + (-sw * so + cw * co * ci) * yp,
    sw * si * xp + cw * si * yp,
  ]
}

/** その時刻（UNIXミリ秒）の天体の位置。衛星は母天体の位置を使う。 */
export function bodyPosition(bodies: Map<string, VoyageBody>, body: VoyageBody, tMs: number): Vec3 {
  const orbit = body.orbit
  if (orbit.kind === 'fixed') return orbit.position_au
  if (orbit.kind === 'jpl_planet') {
    const cy = (tMs - J2000_MS) / DAY_MS / 36525
    const at = (pair: [number, number]) => pair[0] + pair[1] * cy
    const longPeri = at(orbit.long_perihelion)
    const node = at(orbit.long_node)
    const fRad = orbit.f * cy * DEG
    const meanAnomaly = at(orbit.mean_longitude) - longPeri + orbit.b * cy * cy + orbit.c * Math.cos(fRad) + orbit.s * Math.sin(fRad)
    return keplerPosition(at(orbit.a), at(orbit.e), at(orbit.i), node, longPeri - node, meanAnomaly)
  }
  if (orbit.kind === 'kepler') {
    const days = (tMs - isoToMs(orbit.epoch)) / DAY_MS
    const meanAnomaly = orbit.mean_anomaly_deg + orbit.mean_motion_deg_per_day * days
    return keplerPosition(orbit.a_au, orbit.e, orbit.i_deg, orbit.node_deg, orbit.peri_deg, meanAnomaly)
  }
  const parent = body.parent_id ? bodies.get(body.parent_id) : undefined
  if (!parent) throw new Error(`circular orbit needs a parent: ${body.id}`)
  const center = bodyPosition(bodies, parent, tMs)
  const theta = (2 * Math.PI * (tMs - isoToMs(orbit.epoch))) / DAY_MS / orbit.period_days
  const side = cross(orbit.normal, orbit.r0)
  const offset = add(scale(orbit.r0, Math.cos(theta)), scale(side, Math.sin(theta)))
  return add(center, scale(offset, orbit.orbit_radius_km / AU_KM))
}
