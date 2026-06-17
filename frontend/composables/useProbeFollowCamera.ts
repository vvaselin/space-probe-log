import * as THREE from 'three'
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export function useProbeFollowCamera(camera: THREE.PerspectiveCamera, controls: OrbitControls, initialProbePosition: THREE.Vector3) {
  let enabled = false
  let lastProbePosition = initialProbePosition.clone()
  let tween: { start: THREE.Vector3; end: THREE.Vector3; targetStart: THREE.Vector3; targetEnd: THREE.Vector3; t: number } | null = null

  const setEnabled = (nextEnabled: boolean, probePosition: THREE.Vector3) => {
    if (enabled === nextEnabled) return
    enabled = nextEnabled
    tween = null
    lastProbePosition.copy(probePosition)
    if (!enabled) return
    const targetEnd = probePosition.clone()
    const targetShift = targetEnd.clone().sub(controls.target)
    tween = {
      start: camera.position.clone(),
      end: camera.position.clone().add(targetShift),
      targetStart: controls.target.clone(),
      targetEnd,
      t: 0,
    }
  }

  const update = (probePosition: THREE.Vector3) => {
    if (tween) {
      tween.t = Math.min(1, tween.t + 0.045)
      const eased = 1 - Math.pow(1 - tween.t, 3)
      camera.position.lerpVectors(tween.start, tween.end, eased)
      controls.target.lerpVectors(tween.targetStart, tween.targetEnd, eased)
      if (tween.t >= 1) {
        tween = null
        const catchUpDelta = probePosition.clone().sub(controls.target)
        camera.position.add(catchUpDelta)
        controls.target.copy(probePosition)
        lastProbePosition.copy(probePosition)
      }
      return
    }
    if (!enabled) return
    const probeDelta = probePosition.clone().sub(lastProbePosition)
    camera.position.add(probeDelta)
    controls.target.copy(probePosition)
    lastProbePosition.copy(probePosition)
  }

  return {
    isEnabled: () => enabled,
    setEnabled,
    update,
  }
}
