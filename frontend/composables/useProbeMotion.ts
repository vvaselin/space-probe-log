import * as THREE from 'three'
import type { MapPayload } from '~/types/api'
import { addScaledVector, clampToSegment, squaredDistance } from '~/utils/navigationInterpolation'

type ProbeSnapshot = {
  position: THREE.Vector3
  receivedAt: number
  sampledAt: string | null
  timeScale: number
  active: boolean
  phase: string
  targetId: string | null
  origin: THREE.Vector3 | null
  destination: THREE.Vector3 | null
  displayVelocity: THREE.Vector3
}

function vectorFrom(point: { x: number; y: number; z: number }) {
  return new THREE.Vector3(point.x, point.y, point.z)
}

function pointFrom(vector: THREE.Vector3) {
  return { x: vector.x, y: vector.y, z: vector.z }
}

function snapshotFromPayload(payload: MapPayload): ProbeSnapshot {
  const navigation = payload.probe.navigation
  const navPosition = navigation?.display_position
  const position = navPosition ? vectorFrom(navPosition) : vectorFrom(payload.probe)
  const timeScale = payload.clock?.clock_state === 'paused' ? 0 : payload.clock?.time_scale ?? 1
  return {
    position,
    receivedAt: performance.now(),
    sampledAt: navigation?.sampled_at ?? null,
    timeScale,
    active: Boolean(navigation?.active),
    phase: navigation?.phase ?? 'idle',
    targetId: navigation?.destination_system_id ?? payload.probe.target_id ?? null,
    origin: navigation?.origin_display_position ? vectorFrom(navigation.origin_display_position) : null,
    destination: navigation?.destination_display_position ? vectorFrom(navigation.destination_display_position) : null,
    displayVelocity: navigation?.display_velocity ? vectorFrom(navigation.display_velocity) : new THREE.Vector3(),
  }
}

export function useProbeMotion(initialPayload: MapPayload) {
  let snapshot = snapshotFromPayload(initialPayload)
  const renderedPosition = snapshot.position.clone()
  const correctionRate = 10
  const snapDistance = 16
  let paused = snapshot.timeScale === 0

  const authoritativePosition = (now: number) => {
    if (paused || snapshot.timeScale === 0 || !snapshot.active || snapshot.phase === 'arrived') return snapshot.position.clone()
    const elapsedRealSeconds = Math.max(0, (now - snapshot.receivedAt) / 1000)
    const elapsedSimulationSeconds = elapsedRealSeconds * snapshot.timeScale
    const predictedPoint = addScaledVector(pointFrom(snapshot.position), pointFrom(snapshot.displayVelocity), elapsedSimulationSeconds)
    if (snapshot.origin && snapshot.destination) {
      return vectorFrom(clampToSegment(pointFrom(snapshot.origin), pointFrom(snapshot.destination), predictedPoint))
    }
    return vectorFrom(predictedPoint)
  }

  const updateSnapshot = (payload: MapPayload) => {
    const now = performance.now()
    const previousPredictedPosition = authoritativePosition(now)
    const next = snapshotFromPayload(payload)
    const nextPaused = next.timeScale === 0
    const destinationChanged = snapshot.targetId !== next.targetId
    const arrived = next.phase === 'arrived'
    const deactivated = snapshot.active && !next.active
    const wasInactive = !snapshot.active && next.active
    const tooFar = squaredDistance(pointFrom(renderedPosition), pointFrom(next.position)) > snapDistance * snapDistance
    if (nextPaused) {
      paused = true
      snapshot = next
      renderedPosition.copy(next.position)
      snapshot.position.copy(renderedPosition)
      snapshot.receivedAt = now
      return
    }
    if (destinationChanged || arrived || deactivated || wasInactive || tooFar) {
      paused = false
      snapshot = next
      renderedPosition.copy(next.destination && arrived ? next.destination : next.position)
      return
    }
    paused = false
    snapshot = {
      ...next,
      position: next.active ? previousPredictedPosition : next.position,
      receivedAt: now,
    }
  }

  const setTimeScale = (timeScale: number) => {
    const now = performance.now()
    if (timeScale === 0) {
      pauseMotion(now)
      return
    }
    resumeMotion(timeScale, now)
  }

  const pauseMotion = (now = performance.now()) => {
    const frozenPosition = authoritativePosition(now)
    renderedPosition.copy(frozenPosition)
    snapshot = {
      ...snapshot,
      position: frozenPosition,
      receivedAt: now,
      timeScale: 0,
    }
    paused = true
  }

  const resumeMotion = (timeScale: number, now = performance.now()) => {
    snapshot = {
      ...snapshot,
      position: renderedPosition.clone(),
      receivedAt: now,
      timeScale,
    }
    paused = false
  }

  const updateFrame = (deltaSeconds: number, now = performance.now()) => {
    if (paused || snapshot.timeScale === 0) return renderedPosition
    const target = authoritativePosition(now)
    if (snapshot.phase === 'arrived' || !snapshot.active) {
      renderedPosition.copy(target)
      return renderedPosition
    }
    const alpha = 1 - Math.exp(-correctionRate * deltaSeconds)
    renderedPosition.lerp(target, alpha)
    return renderedPosition
  }

  return {
    renderedPosition,
    updateSnapshot,
    setTimeScale,
    pauseMotion,
    resumeMotion,
    updateFrame,
  }
}
