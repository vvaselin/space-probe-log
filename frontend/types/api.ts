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
  probe: { id: string; name: string; x: number; y: number; z: number; system_id: string; target_id?: string | null }
  route: Array<{ x: number; y: number; z: number }>
  route_prediction?: { target_id: string; target_name: string; from: { x: number; y: number; z: number }; to: { x: number; y: number; z: number } } | null
  primary_route_prediction?: { target_id: string; target_name: string; from: { x: number; y: number; z: number }; to: { x: number; y: number; z: number } } | null
  navigation_intent?: 'main_route' | 'detour_signal' | 'survey' | 'resource' | 'recovery' | string | null
  map_origin?: { id: string; name: string; x: number; y: number; z: number }
  focus?: { x: number; y: number; z: number }
  distant_stars?: Array<{ id: string; x: number; y: number; z: number; size: number; brightness: number; color: string }>
  real_data_epoch?: string | null
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
    speed_setting: string
    progress: number
    remaining_distance: number
  } | null
  mission_clock: string
  sim_timestamp: string
  sim_elapsed_seconds: number
}

export interface PromptSettings {
  id: number
  probe_profile: string
  action_policy: string
  log_writer_style: string
  updated_at: string
}
