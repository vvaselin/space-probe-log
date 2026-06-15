<script setup lang="ts">
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { MapPayload } from '~/types/api'

const props = defineProps<{ payload: MapPayload; compact?: boolean; followTick?: number; hideToolbar?: boolean }>()
const selected = ref<string>('未選択')
const host = ref<HTMLDivElement | null>(null)
let cleanup: (() => void) | null = null
let followProbe: (() => void) | null = null

type Selectable = THREE.Object3D & { userData: { label: string } }

function vectorFrom(point: { x: number; y: number; z: number }) {
  return new THREE.Vector3(point.x, point.y, point.z)
}

onMounted(() => {
  if (!host.value) return
  const width = host.value.clientWidth
  const height = host.value.clientHeight
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x030812)
  scene.fog = new THREE.FogExp2(0x030812, 0.0022)

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 3000)
  const focus = props.payload.focus ? vectorFrom(props.payload.focus) : vectorFrom(props.payload.probe)
  camera.position.copy(focus.clone().add(new THREE.Vector3(props.compact ? 26 : 52, props.compact ? 18 : 34, props.compact ? 34 : 66)))

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.75
  host.value.appendChild(renderer.domElement)

  scene.add(new THREE.AmbientLight(0xd7e7ff, 0.76))
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.9)
  keyLight.position.set(28, 40, 32)
  scene.add(keyLight)
  const fillLight = new THREE.PointLight(0xa8ddff, 1.35, 300)
  fillLight.position.copy(focus.clone().add(new THREE.Vector3(0, 18, 24)))
  scene.add(fillLight)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 4
  controls.maxDistance = 1100
  controls.target.copy(focus)

  const selectable: Selectable[] = []
  const systemMaterial = new THREE.MeshStandardMaterial({ color: 0xffd166, emissive: 0x775012, roughness: 0.42 })
  const farObjectiveMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff })
  const waypointMaterial = new THREE.MeshBasicMaterial({ color: 0xdbeafe, transparent: true, opacity: 0.92 })
  const planetMaterial = new THREE.MeshStandardMaterial({ color: 0x58a7ff, emissive: 0x0e2f62, roughness: 0.68 })
  const earthMaterial = new THREE.MeshStandardMaterial({ color: 0x6ee7b7, emissive: 0x105640, roughness: 0.55 })
  const lifeMaterial = new THREE.MeshStandardMaterial({ color: 0x78f5bd, emissive: 0x0d4b33, roughness: 0.55 })
  const signalMaterial = new THREE.MeshStandardMaterial({ color: 0xff5c8a, emissive: 0x7a1230, roughness: 0.3 })
  const probeMaterial = new THREE.MeshStandardMaterial({ color: 0xf8fbff, emissive: 0x244a8f, roughness: 0.35, metalness: 0.25 })

  const starPositions: number[] = []
  const starColors: number[] = []
  const color = new THREE.Color()
  for (const star of props.payload.distant_stars ?? []) {
    starPositions.push(star.x, star.y, star.z)
    color.set(star.color)
    starColors.push(color.r * star.brightness, color.g * star.brightness, color.b * star.brightness)
  }
  const starGeometry = new THREE.BufferGeometry()
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3))
  starGeometry.setAttribute('color', new THREE.Float32BufferAttribute(starColors, 3))
  const starPoints = new THREE.Points(
    starGeometry,
    new THREE.PointsMaterial({
      size: 1.25,
      vertexColors: true,
      transparent: true,
      opacity: 0.96,
      sizeAttenuation: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  )
  scene.add(starPoints)

  for (const system of props.payload.systems) {
    const isFarObjective = system.object_role === 'far_objective'
    const isWaypoint = system.object_role === 'navigation_waypoint'
    const material = isWaypoint ? waypointMaterial : isFarObjective ? farObjectiveMaterial : system.has_life ? lifeMaterial : systemMaterial
    const radius = isWaypoint ? 0.72 : isFarObjective ? 1.8 : system.id === 'sol' ? 1.45 : 1.05
    const geometry = isWaypoint ? new THREE.OctahedronGeometry(radius, 0) : new THREE.SphereGeometry(radius, 32, 20)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.set(system.x, system.y, system.z)
    mesh.userData.label = `${system.name} (${system.id})`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)

    const ringColor = isWaypoint ? 0xdbeafe : isFarObjective ? 0xffffff : system.has_life ? 0x6df2b2 : 0xffd166
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius + 0.45, radius + 0.6, 64),
      new THREE.MeshBasicMaterial({ color: ringColor, transparent: true, opacity: isWaypoint ? 0.45 : isFarObjective ? 0.62 : 0.3, side: THREE.DoubleSide })
    )
    ring.position.copy(mesh.position)
    ring.rotation.x = Math.PI / 2
    scene.add(ring)
  }

  for (const body of props.payload.bodies) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(Math.max(0.24, body.radius * 1.05), 24, 16),
      body.object_role === 'origin_body' ? earthMaterial : planetMaterial
    )
    mesh.position.set(body.x, body.y, body.z)
    mesh.userData.label = `${body.name} / ${body.type}`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
  }

  for (const signal of props.payload.signals) {
    const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(signal.investigated ? 0.34 : 0.52), signalMaterial)
    mesh.position.set(signal.x, signal.y, signal.z)
    mesh.userData.label = `${signal.id} / ${signal.kind}`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
  }

  const probe = new THREE.Mesh(new THREE.ConeGeometry(0.7, 1.7, 4), probeMaterial)
  const probeAnchor = vectorFrom(props.payload.probe)
  const probePosition = probeAnchor.clone().add(new THREE.Vector3(0.45, 0.95, 0.35))
  probe.position.copy(probePosition)
  probe.userData.label = props.payload.probe.name
  scene.add(probe)
  selectable.push(probe as unknown as Selectable)

  const probeMarker = new THREE.Mesh(
    new THREE.RingGeometry(1.05, 1.16, 40),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.86, side: THREE.DoubleSide })
  )
  probeMarker.position.copy(probeAnchor)
  probeMarker.rotation.x = Math.PI / 2
  scene.add(probeMarker)

  const origin = props.payload.map_origin
  if (origin) {
    const originPoint = vectorFrom(origin)
    const outward = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([originPoint, probeMarker.position.clone()]),
      new THREE.LineBasicMaterial({ color: 0xa7c8ff, transparent: true, opacity: 0.32 })
    )
    scene.add(outward)
  }

  if (props.payload.route.length >= 2) {
    const points = props.payload.route.map((point) => new THREE.Vector3(point.x, point.y, point.z))
    const routePoints = points.length >= 4 ? new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.35).getPoints(points.length * 10) : points
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(routePoints), new THREE.LineBasicMaterial({ color: 0x9fffe6, transparent: true, opacity: 0.9 })))
  }

  if (props.payload.route_prediction) {
    const prediction = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([vectorFrom(props.payload.route_prediction.from), vectorFrom(props.payload.route_prediction.to)]),
      new THREE.LineDashedMaterial({ color: 0xdbeafe, transparent: true, opacity: 0.42, dashSize: 2.2, gapSize: 1.5 })
    )
    prediction.computeLineDistances()
    scene.add(prediction)
  }

  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  const click = (event: MouseEvent) => {
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObjects(selectable)[0]
    if (hit) selected.value = hit.object.userData.label
  }
  renderer.domElement.addEventListener('click', click)

  const resize = () => {
    if (!host.value) return
    camera.aspect = host.value.clientWidth / host.value.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(host.value.clientWidth, host.value.clientHeight)
  }
  window.addEventListener('resize', resize)

  let cameraTween: { start: THREE.Vector3; end: THREE.Vector3; targetStart: THREE.Vector3; targetEnd: THREE.Vector3; t: number } | null = null
  followProbe = () => {
    selected.value = props.payload.probe.name
    const targetEnd = vectorFrom(props.payload.probe)
    const offset = new THREE.Vector3(16, 11, 22)
    cameraTween = {
      start: camera.position.clone(),
      end: targetEnd.clone().add(offset),
      targetStart: controls.target.clone(),
      targetEnd,
      t: 0,
    }
  }

  let frame = 0
  const animate = () => {
    frame = requestAnimationFrame(animate)
    probe.rotation.y += 0.014
    probeMarker.rotation.z += 0.01
    if (cameraTween) {
      cameraTween.t = Math.min(1, cameraTween.t + 0.045)
      const eased = 1 - Math.pow(1 - cameraTween.t, 3)
      camera.position.lerpVectors(cameraTween.start, cameraTween.end, eased)
      controls.target.lerpVectors(cameraTween.targetStart, cameraTween.targetEnd, eased)
      if (cameraTween.t >= 1) cameraTween = null
    }
    const distance = camera.position.distanceTo(controls.target)
    starPoints.visible = distance > 8
    controls.update()
    renderer.render(scene, camera)
  }
  animate()

  cleanup = () => {
    cancelAnimationFrame(frame)
    renderer.domElement.removeEventListener('click', click)
    window.removeEventListener('resize', resize)
    renderer.dispose()
    starGeometry.dispose()
    host.value?.replaceChildren()
    followProbe = null
  }
})

watch(() => props.followTick, () => followProbe?.())
onBeforeUnmount(() => cleanup?.())
</script>

<template>
  <div>
    <div ref="host" class="map-frame" :class="{ 'map-compact': compact }" />
    <div v-if="!hideToolbar" class="map-toolbar">
      <button type="button" @click="followProbe?.()">探査機を追尾</button>
      <span class="map-chip">選択: {{ selected }}</span>
      <span class="map-legend map-legend--star">恒星系</span>
      <span class="map-legend map-legend--waypoint">航行点</span>
      <span class="map-legend map-legend--planet">天体</span>
      <span class="map-legend map-legend--signal">信号</span>
    </div>
  </div>
</template>
