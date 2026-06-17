export type VectorLike = { x: number; y: number; z: number }

export function cloneVector(value: VectorLike): VectorLike {
  return { x: value.x, y: value.y, z: value.z }
}

export function addScaledVector(base: VectorLike, velocity: VectorLike, seconds: number): VectorLike {
  return {
    x: base.x + velocity.x * seconds,
    y: base.y + velocity.y * seconds,
    z: base.z + velocity.z * seconds,
  }
}

export function squaredDistance(a: VectorLike, b: VectorLike): number {
  const dx = a.x - b.x
  const dy = a.y - b.y
  const dz = a.z - b.z
  return dx * dx + dy * dy + dz * dz
}

export function clampToSegment(origin: VectorLike, destination: VectorLike, point: VectorLike): VectorLike {
  const vx = destination.x - origin.x
  const vy = destination.y - origin.y
  const vz = destination.z - origin.z
  const lengthSq = vx * vx + vy * vy + vz * vz
  if (lengthSq <= 1e-9) return cloneVector(destination)
  const t = ((point.x - origin.x) * vx + (point.y - origin.y) * vy + (point.z - origin.z) * vz) / lengthSq
  const clamped = Math.max(0, Math.min(1, t))
  return {
    x: origin.x + vx * clamped,
    y: origin.y + vy * clamped,
    z: origin.z + vz * clamped,
  }
}
