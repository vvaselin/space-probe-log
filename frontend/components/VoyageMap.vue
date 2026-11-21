<script setup lang="ts">
// 再設計版の航行マップ（11章）。位置はバックから受け取らず、区間の式・時刻表・軌道要素から毎フレーム計算する。
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useProbeFollowCamera } from '~/composables/useProbeFollowCamera'
import { displayRadius, pushesFor, toDisplay, toScene, type Push } from '~/utils/voyage/display'
import { legDepartMs, legDurationS, legPositionAt, probePosition } from '~/utils/voyage/motion'
import { bodyPosition } from '~/utils/voyage/orbits'
import { simTimeAt } from '~/utils/voyage/timetable'
import type { LegFormula, Vec3, VoyageSync } from '~/utils/voyage/types'

const props = defineProps<{ sync: VoyageSync; now: () => number }>()
const emit = defineEmits<{ correction: [size: number] }>()
const host = ref<HTMLDivElement | null>(null)

// 表示用の色だけをフロントに持つ（バックの見た目のデータはLLM向けの言葉）
const COLORS: Record<string, number> = {
  sun: 0xffd27a, mercury: 0x9e9a94, venus: 0xe8d9a8, earth: 0x4f8fdc, moon: 0xb8b8b8, mars: 0xc4623a,
  phobos: 0x7a6e66, ceres: 0x8a8a86, vesta: 0xb3aea5, jupiter: 0xd8b98c, io: 0xe8cf4a, europa: 0xd9d2c2,
  ganymede: 0x9c958a, callisto: 0x6f665c, saturn: 0xe3cf98, mimas: 0xc8c8c4, enceladus: 0xf4f8ff, titan: 0xd99a3c,
  iapetus: 0x8f8a80, uranus: 0x9fd8de, miranda: 0xa8a8a8, ariel: 0xc2c2c2, titania: 0xa89f99, neptune: 0x3f6fd8,
  triton: 0xe3cfcf, pluto: 0xd8c2a8, charon: 0x9a8f88, haumea: 0xeeeeee, makemake: 0xc98d6e, eris: 0xf2f2f2,
  sedna: 0xb8483a, arrokoth: 0xa0563a,
}
const CORRECTION_MS = 1500 // 式や時計の更新で位置がずれた時、この時間をかけて寄せる
const LEG_LINE_POINTS = 120

function makeLabel(text: string): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.font = '28px sans-serif'
    ctx.fillStyle = '#dbe7ff'
    ctx.textAlign = 'center'
    ctx.fillText(text, 128, 40)
  }
  const material = new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false, sizeAttenuation: false, transparent: true })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(0.12, 0.03, 1)
  return sprite
}

const easeOutCubic = (k: number) => 1 - (1 - k) ** 3
let dispose: (() => void) | null = null

onMounted(() => {
  const el = host.value
  if (!el) return
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.setSize(el.clientWidth, el.clientHeight)
  el.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x02040a)
  const camera = new THREE.PerspectiveCamera(50, el.clientWidth / el.clientHeight, 0.01, 2000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  scene.add(new THREE.AmbientLight(0xffffff, 0.25))
  const sunLight = new THREE.PointLight(0xfff2d6, 3, 0, 0)
  scene.add(sunLight)

  const bodyMeshes = new Map<string, THREE.Mesh>()
  for (const body of props.sync.bodies) {
    const radius = displayRadius(body)
    const color = COLORS[body.id] ?? 0xaaaaaa
    const material = body.subtype === 'star' ? new THREE.MeshBasicMaterial({ color }) : new THREE.MeshStandardMaterial({ color, roughness: 0.9 })
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 16), material)
    const label = makeLabel(body.name)
    label.position.set(0, radius + 0.2, 0)
    mesh.add(label)
    scene.add(mesh)
    bodyMeshes.set(body.id, mesh)
  }
  const probe = new THREE.Mesh(new THREE.OctahedronGeometry(0.1), new THREE.MeshBasicMaterial({ color: 0x7cf7ff }))
  const probeLabel = makeLabel('INSOMNIA-07')
  probeLabel.position.set(0, 0.3, 0)
  probe.add(probeLabel)
  scene.add(probe)
  const legLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x7cf7ff, transparent: true, opacity: 0.45 }))
  scene.add(legLine)

  const frameState = (realMs: number) => {
    const sync = props.sync
    const bodiesById = new Map(sync.bodies.map((b) => [b.id, b]))
    const simMs = simTimeAt(sync.timetable, realMs)
    const positions = new Map(sync.bodies.map((b) => [b.id, bodyPosition(bodiesById, b, simMs)]))
    const pushes = pushesFor(sync.bodies, positions)
    const { position, leg } = probePosition(sync.legs, sync.start_position_au, simMs)
    return { positions, pushes, leg, probe: new THREE.Vector3(...toScene(toDisplay(position, pushes))) }
  }

  const updateLegLine = (leg: LegFormula | null, pushes: Push[]) => {
    if (!leg) return
    const start = legDepartMs(leg.profile)
    const duration = legDurationS(leg.profile) * 1000
    const points: number[] = []
    for (let i = 0; i <= LEG_LINE_POINTS; i++) {
      const p: Vec3 = legPositionAt(leg.profile, start + (duration * i) / LEG_LINE_POINTS)
      points.push(...toScene(toDisplay(p, pushes)))
    }
    legLine.geometry.dispose()
    legLine.geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(points, 3))
  }

  const initial = frameState(props.now())
  probe.position.copy(initial.probe)
  camera.position.copy(initial.probe).add(new THREE.Vector3(4, 3, 6))
  controls.target.copy(initial.probe)
  const follow = useProbeFollowCamera(camera, controls, initial.probe)
  follow.setEnabled(true, initial.probe)

  // 新しい同期の材料が来たら、今の表示位置との差を記録し、飛ばさずに寄せる
  let correction: { offset: THREE.Vector3; startedAt: number } | null = null
  const stopSyncWatch = watch(
    () => props.sync,
    () => {
      const next = frameState(props.now()).probe
      const offset = probe.position.clone().sub(next)
      const size = offset.length()
      if (size > 1e-6) {
        correction = { offset, startedAt: performance.now() }
        console.info(`[voyage] 位置の補正 ${size.toFixed(4)} 表示単位`)
        emit('correction', size)
      }
    },
  )

  let frame = 0
  let frameCount = 0
  const animate = () => {
    frame = requestAnimationFrame(animate)
    const state = frameState(props.now())
    for (const [id, mesh] of bodyMeshes) {
      const p = state.positions.get(id)
      if (p) mesh.position.set(...toScene(toDisplay(p, state.pushes)))
    }
    sunLight.position.copy(bodyMeshes.get('sun')?.position ?? new THREE.Vector3())
    const target = state.probe
    if (correction) {
      const k = (performance.now() - correction.startedAt) / CORRECTION_MS
      if (k >= 1) correction = null
      else target.add(correction.offset.clone().multiplyScalar(1 - easeOutCubic(k)))
    }
    probe.position.copy(target)
    if (frameCount++ % 30 === 0) updateLegLine(state.leg, state.pushes)
    follow.update(probe.position)
    controls.update()
    renderer.render(scene, camera)
  }
  animate()

  const resize = () => {
    camera.aspect = el.clientWidth / el.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(el.clientWidth, el.clientHeight)
  }
  window.addEventListener('resize', resize)

  dispose = () => {
    cancelAnimationFrame(frame)
    stopSyncWatch()
    window.removeEventListener('resize', resize)
    controls.dispose()
    scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite) {
        object.geometry.dispose()
        const material = object.material as THREE.Material & { map?: THREE.Texture | null }
        material.map?.dispose()
        material.dispose()
      }
    })
    renderer.dispose()
    renderer.domElement.remove()
  }
})

onBeforeUnmount(() => dispose?.())
</script>

<template>
  <div ref="host" class="voyage-map" />
</template>

<style scoped>
.voyage-map {
  width: 100%;
  height: 70vh;
  min-height: 420px;
  border: 1px solid #1c2a44;
  border-radius: 6px;
  overflow: hidden;
}
</style>
