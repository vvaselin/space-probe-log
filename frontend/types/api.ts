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
  observations: Array<{ type: string; value: string; reliability: number }>
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
  systems: Array<{ id: string; name: string; x: number; y: number; z: number; has_life: boolean; kind?: string; object_role?: string }>
  bodies: Array<{ id: string; system_id: string; name: string; type: string; x: number; y: number; z: number; radius: number; object_role?: string }>
  signals: Array<{ id: string; system_id: string; kind: string; x: number; y: number; z: number; investigated: boolean; object_role?: string }>
  probe: { id: string; name: string; x: number; y: number; z: number; system_id: string; target_id?: string | null }
  route: Array<{ x: number; y: number; z: number }>
  route_prediction?: { target_id: string; target_name: string; from: { x: number; y: number; z: number }; to: { x: number; y: number; z: number } } | null
  map_origin?: { id: string; name: string; x: number; y: number; z: number }
  focus?: { x: number; y: number; z: number }
  distant_stars?: Array<{ id: string; x: number; y: number; z: number; size: number; brightness: number; color: string }>
}

export interface SimulationStep {
  action: Record<string, unknown>
  event: { id: number; event_type: string; summary: string; mission_time: number }
  log: LogListItem
  probe: Probe
}

export interface PromptSettings {
  id: number
  probe_profile: string
  action_policy: string
  log_writer_style: string
  updated_at: string
}
