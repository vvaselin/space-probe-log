export interface Probe {
  id: string
  name: string
  current_system_id: string
  target_id: string | null
  x: number
  y: number
  z: number
  display_x: number
  display_y: number
  display_z: number
  velocity: number
  energy: number
  fuel: number
  hull: number
  communication: number
  sensors: number
  propulsion: number
  storage_used: number
  storage_capacity: number
  collected_resources: Record<string, number>
  discovered_body_ids: string[]
  current_mission: string
  last_updated_at: string
  mission_time: number
  mission_clock: string
  sim_timestamp: string
  sim_elapsed_seconds: number
  specification?: ProbeSpecification | null
  navigation?: ProbeNavigation | null
  simulation_datetime?: string | null
}

export interface LogListItem {
  id: number
  title: string
  summary: string
  log_type: string
  mission_time: number
  generated_at: string
  probe_position: Record<string, unknown>
  reliability: number
}

export interface LogDetail extends LogListItem {
  body_markdown: string
  related_event_ids: number[]
  related_body_ids: string[]
  probe_state_snapshot: Record<string, unknown>
  communication_status: string
  observations: Array<{
    type: string
    value: string
    reliability: number
    sighting_level?: 'detected' | 'resolved' | 'confirmed'
    source?: string | null
    distance_hint?: string | null
  }>
  interpretations: Array<{ hypothesis: string; confidence: number }>
}

export interface StarSystem {
  id: string
  name: string
  kind: string
  x: number
  y: number
  z: number
  display_x: number
  display_y: number
  display_z: number
  discovered: boolean
  generated_seed: string
  has_life: boolean
  resources: Record<string, number>
  details: Record<string, unknown>
}

export interface MapPayload {
  systems: Array<{
    id: string
    name: string
    x: number
    y: number
    z: number
    has_life: boolean
    kind?: string
    object_role?: string
    source?: 'jpl_horizons' | 'nasa_exoplanet_archive' | 'generated' | 'manual' | string
    visual_data?: {
      texture_key?: string
      color_profile?: string[]
      opacity?: number
      emissive?: string
      emission_strength?: number
      albedo_color?: string
      roughness?: number
      ring?: {
        inner_radius?: number
        outer_radius?: number
        texture_key?: string
        tilt?: number
        opacity?: number
        color?: string
      }
    }
  }>
  bodies: Array<{
    id: string
    system_id: string
    name: string
    type: string
    x: number
    y: number
    z: number
    radius: number
    physical_radius_km?: number
    display_radius?: number
    object_role?: string
    source?: 'jpl_horizons' | 'nasa_exoplanet_archive' | 'generated' | 'manual' | string
    visual_data?: {
      texture_key?: string
      color_profile?: string[]
      opacity?: number
      emissive?: string
      emission_strength?: number
      albedo_color?: string
      roughness?: number
      ring?: {
        inner_radius?: number
        outer_radius?: number
        texture_key?: string
        tilt?: number
        opacity?: number
        color?: string
      }
    }
  }>
  signals: Array<{ id: string; system_id: string; kind: string; x: number; y: number; z: number; investigated: boolean; object_role?: string }>
  environment_objects?: Array<{
    id: string
    name: string
    object_type: 'nebula' | 'dust_cloud' | 'anomaly_region' | string
    x: number
    y: number
    z: number
    scale: { x: number; y: number; z: number }
    rotation: { x: number; y: number; z: number }
    source?: string
    nebula_type?: string
    visual_data?: {
      texture_key?: string
      color_profile?: string[]
      opacity?: number
      emission_strength?: number
      emissive?: string
    }
    details?: Record<string, unknown>
  }>
  probe: { id: string; name: string; x: number; y: number; z: number; system_id: string; target_id?: string | null; navigation?: ProbeNavigation; specification?: ProbeSpecification }
  route: Array<{ x: number; y: number; z: number }>
  route_prediction?: { target_id: string; target_name: string; from: { x: number; y: number; z: number }; to: { x: number; y: number; z: number } } | null
  primary_route_prediction?: { target_id: string; target_name: string; from: { x: number; y: number; z: number }; to: { x: number; y: number; z: number } } | null
  navigation_intent?: 'main_route' | 'detour_signal' | 'survey' | 'resource' | 'recovery' | string | null
  map_origin?: { id: string; name: string; x: number; y: number; z: number }
  focus?: { x: number; y: number; z: number }
  distant_stars?: Array<{ id: string; x: number; y: number; z: number; size: number; brightness: number; color: string }>
  real_data_epoch?: string | null
  clock?: { simulation_datetime: string; time_scale: number; clock_state: ClockState | string }
}

export interface SimulationStep {
  action: Record<string, unknown>
  event: { id: number; event_type: string; summary: string; mission_time: number; mission_clock?: string; sim_timestamp?: string; sim_elapsed_seconds?: number }
  log: LogListItem
  probe: Probe
  mission_clock?: string
  sim_timestamp?: string
  sim_elapsed_seconds?: number
}

export interface SimulationTick {
  action: Record<string, unknown>
  event: { id: number; event_type: string; summary: string; mission_time: number; log_worthy: boolean; mission_clock: string; sim_timestamp: string; sim_elapsed_seconds: number }
  log: LogListItem | null
  probe: Probe
  route: {
    target_id: string
    target_name: string
    phase: 'course_plotted' | 'accelerating' | 'cruising' | 'decelerating' | 'arrived' | string
    velocity: number
    current_speed_m_s?: number
    speed_setting: string
    drive_mode?: string
    progress: number
    remaining_distance: number
    remaining_distance_km?: number
    remaining_distance_pc?: number
    eta_datetime?: string
  } | null
  mission_clock: string
  sim_timestamp: string
  sim_elapsed_seconds: number
}

export type DriveMode = 'conventional' | 'piano_drive'
export type NavigationPhase = 'idle' | 'local_navigation' | 'system_departure' | 'accelerating' | 'interstellar_cruise' | 'decelerating' | 'system_arrival' | 'arrived'
export type ClockState = 'running' | 'paused'

export interface ProbeSpecification {
  id: string
  display_name: string
  vessel_type: string
  length_m: number
  width_m: number
  height_m: number
  deployed_max_width_m: number
  launch_mass_kg: number
  dry_mass_kg: number
  propellant_mass_kg: number
  repair_resource_feedstock_kg: number
  cruise_speed_fraction_c: number
  cruise_speed_m_s: number
  cruise_speed_km_s: number
  max_cruise_speed_fraction_c: number
  max_cruise_speed_m_s: number
  max_cruise_speed_km_s: number
  planned_operational_years: number
  local_drive_mode: DriveMode
  interstellar_drive_mode: DriveMode
  defense: string
  capabilities: string[]
}

export interface ProbeNavigation {
  active: boolean
  phase: NavigationPhase | string
  drive_mode: DriveMode | string
  origin_system_id?: string | null
  destination_system_id?: string | null
  destination_name?: string | null
  started_at?: string | null
  eta_datetime?: string | null
  arrived_at?: string | null
  sampled_at?: string | null
  total_distance_pc: number
  total_distance_km: number
  remaining_distance_pc: number
  remaining_distance_km: number
  progress: number
  progress_percent: number
  current_speed_m_s: number
  current_speed_km_s: number
  cruise_speed_m_s: number
  max_speed_m_s: number
  galactic_position_pc?: { x: number; y: number; z: number } | null
  local_position_au?: { x: number; y: number; z: number } | null
  display_position?: { x: number; y: number; z: number } | null
  origin_display_position?: { x: number; y: number; z: number } | null
  destination_display_position?: { x: number; y: number; z: number } | null
  display_velocity?: { x: number; y: number; z: number } | null
}

export interface SimulationClock {
  simulation_datetime: string
  mission_clock: string
  time_scale: number
  clock_state: ClockState
  last_real_datetime: string
  real_elapsed_seconds_applied: number
}

export interface SimulationSettings {
  default_time_scale: number
  advance_offline: boolean
  max_offline_elapsed_seconds: number
  time_scale_presets: number[]
  updated_at: string
}

export interface SimulationSettingsUpdate {
  default_time_scale?: number
  advance_offline?: boolean
  max_offline_elapsed_seconds?: number
  time_scale_presets?: number[]
}

export interface PromptSettings {
  id: number
  probe_profile: string
  action_policy: string
  log_writer_style: string
  updated_at: string
}
