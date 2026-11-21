// backend/app/voyage/motion.py の LegProfile と sync.py の probe_position と同じ式。変えたら両方を直す。
import { AU_KM, add, isoToMs, norm, scale, sub } from './orbits.ts'
import type { LegFormula, LegProfile, Vec3 } from './types.ts'

export const legDurationS = (p: LegProfile): number => p.accel_s + p.cruise_s + p.decel_s
export const legDepartMs = (p: LegProfile): number => isoToMs(p.depart_at)
export const legArriveMs = (p: LegProfile): number => legDepartMs(p) + legDurationS(p) * 1000
export const legDistanceKm = (p: LegProfile): number => norm(sub(p.destination_au, p.origin_au)) * AU_KM

export function travelledKm(p: LegProfile, tMs: number): number {
  const v = p.cruise_speed_km_s
  let tau = (tMs - legDepartMs(p)) / 1000
  if (tau <= 0) return 0
  if (tau < p.accel_s) return (0.5 * v * tau * tau) / p.accel_s
  let s = 0.5 * v * p.accel_s
  tau -= p.accel_s
  if (tau < p.cruise_s) return s + v * tau
  s += v * p.cruise_s
  tau -= p.cruise_s
  if (tau < p.decel_s) return s + v * tau - (0.5 * v * tau * tau) / p.decel_s
  return s + 0.5 * v * p.decel_s
}

export function speedAt(p: LegProfile, tMs: number): number {
  const tau = (tMs - legDepartMs(p)) / 1000
  const duration = legDurationS(p)
  if (tau <= 0 || tau >= duration) return 0
  if (tau < p.accel_s) return (p.cruise_speed_km_s * tau) / p.accel_s
  if (tau < p.accel_s + p.cruise_s) return p.cruise_speed_km_s
  return (p.cruise_speed_km_s * (duration - tau)) / p.decel_s
}

// backend/app/voyage/motion.py の state_at と同じ区切り
export function speedStateAt(p: LegProfile, tMs: number): '停止' | '加速中' | '巡航中' | '減速中' {
  const tau = (tMs - legDepartMs(p)) / 1000
  if (tau <= 0 || tau >= legDurationS(p)) return '停止'
  if (tau < p.accel_s) return '加速中'
  if (tau < p.accel_s + p.cruise_s) return '巡航中'
  return '減速中'
}

export function legPositionAt(p: LegProfile, tMs: number): Vec3 {
  const total = legDistanceKm(p)
  if (total === 0) return p.origin_au
  return add(p.origin_au, scale(sub(p.destination_au, p.origin_au), Math.min(1, travelledKm(p, tMs) / total)))
}

/** 区間は前の終点から始まるので、どの時刻でもつながっている。 */
export function probePosition(legs: LegFormula[], start: Vec3, simMs: number): { position: Vec3; leg: LegFormula | null } {
  for (const leg of legs) {
    if (simMs <= legArriveMs(leg.profile)) return { position: legPositionAt(leg.profile, simMs), leg }
  }
  const last = legs.at(-1)
  return last ? { position: last.profile.destination_au, leg: last } : { position: start, leg: null }
}
