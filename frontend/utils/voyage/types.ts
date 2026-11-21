// /api/voyage/sync の形（backend/app/api/voyage.py、backend/app/voyage/sync.py）。物理座標は太陽中心・J2000黄道座標、単位はAU。

export type Vec3 = [number, number, number]

export type JplPlanetOrbit = {
  kind: 'jpl_planet'
  a: [number, number]
  e: [number, number]
  i: [number, number]
  mean_longitude: [number, number]
  long_perihelion: [number, number]
  long_node: [number, number]
  b: number
  c: number
  s: number
  f: number
}

export type KeplerOrbit = {
  kind: 'kepler'
  epoch: string
  a_au: number
  e: number
  i_deg: number
  node_deg: number
  peri_deg: number
  mean_anomaly_deg: number
  mean_motion_deg_per_day: number
}

export type CircularOrbit = {
  kind: 'circular'
  epoch: string
  orbit_radius_km: number
  period_days: number
  r0: Vec3
  normal: Vec3
}

export type FixedOrbit = { kind: 'fixed'; position_au: Vec3 }

export type Orbit = JplPlanetOrbit | KeplerOrbit | CircularOrbit | FixedOrbit

export type VoyageBody = {
  id: string
  name: string
  subtype: string
  parent_id: string | null
  radius_km: number
  orbit: Orbit
}

export type LegProfile = {
  origin_au: Vec3
  destination_au: Vec3
  depart_at: string
  accel_s: number
  cruise_s: number
  decel_s: number
  cruise_speed_km_s: number
}

export type LegFormula = { index: number; target_id: string; profile: LegProfile }

export type TimetablePoint = { real_at: string; sim_at: string; label: string; published: boolean }

export type VoyageSync = {
  server_time: string
  voyage_id: number
  start_position_au: Vec3
  timetable: TimetablePoint[]
  legs: LegFormula[]
  bodies: VoyageBody[]
}

export type VoyagePosition = { real_at: string; sim_at: string; position_au: Vec3; leg_index: number | null }
