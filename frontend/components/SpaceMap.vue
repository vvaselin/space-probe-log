<script setup lang="ts">
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { pickTextureSet } from '~/assets/texture/registry'
import { useProbeFollowCamera } from '~/composables/useProbeFollowCamera'
import { useProbeMotion } from '~/composables/useProbeMotion'
import type { MapPayload } from '~/types/api'

const props = defineProps<{
  payload: MapPayload
  compact?: boolean
  followTick?: number
  followEnabled?: boolean
  paused?: boolean
  hideToolbar?: boolean
}>()
const selected = ref<string>('未選択')
const localFollowEnabled = ref(false)
const host = ref<HTMLDivElement | null>(null)
let cleanup: (() => void) | null = null
let setProbeFollow: ((enabled: boolean) => void) | null = null
type SpaceMapCameraView = {
  compact: boolean
  offset: { x: number; y: number; z: number }
  targetDeltaFromProbe: { x: number; y: number; z: number }
}

function cameraViewStore() {
  return globalThis as typeof globalThis & { __spaceMapCameraView?: SpaceMapCameraView }
}

type Selectable = THREE.Object3D & { userData: { label: string } }
type LodEntry = {
  mesh: THREE.Object3D
  point: THREE.Points
  ring?: THREE.Object3D
  near: number
  far: number
  keepVisible?: boolean
}

function vectorFrom(point: { x: number; y: number; z: number }) {
  return new THREE.Vector3(point.x, point.y, point.z)
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function bodyVisualRadius(body: MapPayload['bodies'][number]) {
  const radiusKm = body.physical_radius_km
  if (!radiusKm || radiusKm <= 0) return Math.max(0.24, body.radius * 1.05)
  const earthRadiusKm = 6371
  return clamp(Math.sqrt(radiusKm / earthRadiusKm) * 0.24, 0.08, body.type === 'star' ? 2.55 : 1.05)
}

function probeVisualLength(payload: MapPayload) {
  const lengthKm = (payload.probe.specification?.length_m ?? 18) / 1000
  return clamp(Math.sqrt(lengthKm / 6371) * 0.24, 0.08, 0.18)
}

onMounted(() => {
  if (!host.value) return
  const width = host.value.clientWidth
  const height = host.value.clientHeight
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x030812)
  scene.fog = new THREE.FogExp2(0x030812, 0.0022)

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 3000)
  const initialProbeAnchor = vectorFrom(props.payload.probe)
  const solarOverview = props.payload.probe.system_id === 'sol' && !props.payload.probe.target_id
  const focus = solarOverview
    ? new THREE.Vector3(0, 0, 0)
    : props.payload.focus
      ? vectorFrom(props.payload.focus)
      : vectorFrom(props.payload.probe)
  camera.position.copy(
    focus.clone().add(
      new THREE.Vector3(
        props.compact ? 13 : solarOverview ? 34 : 26,
        props.compact ? 9 : solarOverview ? 24 : 18,
        props.compact ? 18 : solarOverview ? 48 : 34,
      ),
    ),
  )

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
  controls.minDistance = 1.4
  controls.maxDistance = 1100
  controls.target.copy(focus)
  const savedCameraView = cameraViewStore().__spaceMapCameraView
  if (savedCameraView && savedCameraView.compact === Boolean(props.compact)) {
    const targetDelta = new THREE.Vector3(
      savedCameraView.targetDeltaFromProbe.x,
      savedCameraView.targetDeltaFromProbe.y,
      savedCameraView.targetDeltaFromProbe.z,
    )
    const offset = new THREE.Vector3(savedCameraView.offset.x, savedCameraView.offset.y, savedCameraView.offset.z)
    controls.target.copy(initialProbeAnchor.clone().add(targetDelta))
    camera.position.copy(controls.target.clone().add(offset))
  }

  const selectable: Selectable[] = []
  const lodEntries: LodEntry[] = []
  const targetId = props.payload.probe.target_id ?? props.payload.route_prediction?.target_id ?? null
  const systemMaterial = new THREE.MeshStandardMaterial({ color: 0xffd166, emissive: 0xa56a16, roughness: 0.42 })
  const farObjectiveMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff })
  const waypointMaterial = new THREE.MeshBasicMaterial({ color: 0xdbeafe, transparent: true, opacity: 0.92 })
  const rockyMaterial = new THREE.MeshStandardMaterial({ color: 0xb8a58d, emissive: 0x28190f, roughness: 0.88 })
  const earthMaterial = new THREE.MeshStandardMaterial({ color: 0x5fa8ff, emissive: 0x123d2a, roughness: 0.55 })
  const gasMaterial = new THREE.MeshStandardMaterial({ color: 0x9fc4ff, emissive: 0x233764, roughness: 0.72 })
  const iceMaterial = new THREE.MeshStandardMaterial({ color: 0xbad9ff, emissive: 0x17304c, roughness: 0.62 })
  const moonMaterial = new THREE.MeshStandardMaterial({ color: 0xb7b2ab, emissive: 0x141414, roughness: 0.94 })
  const lifeMaterial = new THREE.MeshStandardMaterial({ color: 0x78f5bd, emissive: 0x0d4b33, roughness: 0.55 })
  const signalMaterial = new THREE.MeshStandardMaterial({ color: 0xff5c8a, emissive: 0x7a1230, roughness: 0.3 })
  const probeMaterial = new THREE.MeshStandardMaterial({ color: 0xf8fbff, emissive: 0x244a8f, roughness: 0.35, metalness: 0.25 })
  const textureLoader = new THREE.TextureLoader()
  const textureCache = new Map<string, THREE.Texture>()
  const loadTexture = (url?: string) => {
    if (!url) return undefined
    const cached = textureCache.get(url)
    if (cached) return cached
    const texture = textureLoader.load(url)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.wrapS = THREE.RepeatWrapping
    texture.wrapT = THREE.RepeatWrapping
    textureCache.set(url, texture)
    return texture
  }
  const texturedStandardMaterial = (textureKey: string | undefined, fallback: THREE.MeshStandardMaterial) => {
    const textureSet = pickTextureSet(textureKey)
    const map = loadTexture(textureSet?.albedo)
    const roughnessMap = loadTexture(textureSet?.roughness)
    const emissionMap = loadTexture(textureSet?.emission)
    if (!map && !roughnessMap && !emissionMap) return fallback
    return new THREE.MeshStandardMaterial({
      color: fallback.color,
      emissive: fallback.emissive,
      roughness: fallback.roughness,
      metalness: fallback.metalness,
      map,
      roughnessMap,
      emissiveMap: emissionMap,
      emissiveIntensity: emissionMap ? 0.75 : 0.25,
    })
  }
  const bodyFallbackMaterial = (body: MapPayload['bodies'][number]) => {
    if (body.type === 'star') return systemMaterial
    if (body.id === 'earth' || body.object_role === 'origin_body') return earthMaterial
    if (body.type === 'gas_giant') return gasMaterial
    if (body.type === 'ice_planet' || body.type === 'ice_world') return iceMaterial
    if (body.type === 'moon' || body.type === 'asteroid' || body.type === 'comet') return moonMaterial
    return rockyMaterial
  }
  const lodColorForBody = (body: MapPayload['bodies'][number]) => {
    if (body.type === 'star') return 0xffefb0
    if (body.id === 'earth' || body.object_role === 'origin_body') return 0xc8fff0
    if (body.type === 'gas_giant') return 0xd7e6ff
    if (body.type === 'ice_planet' || body.type === 'ice_world') return 0xe3f2ff
    if (body.type === 'moon' || body.type === 'asteroid' || body.type === 'comet') return 0xdad6d1
    return 0xf2d3c1
  }
  const cloudMaterials: THREE.ShaderMaterial[] = []
  const cloudMeshes: THREE.Mesh[] = []
  const createCloudMaterial = (options: {
    noise?: THREE.Texture
    mask?: THREE.Texture
    colorA: THREE.Color
    colorB: THREE.Color
    colorC: THREE.Color
    opacity: number
    emissionStrength: number
    nebulaType?: string
    objectType: string
  }) => {
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uNoise: { value: options.noise ?? null },
        uMask: { value: options.mask ?? options.noise ?? null },
        uColorA: { value: options.colorA },
        uColorB: { value: options.colorB },
        uColorC: { value: options.colorC },
        uOpacity: { value: options.opacity },
        uEmissionStrength: { value: options.emissionStrength },
        uTime: { value: 0 },
        uDark: { value: options.objectType === 'dust_cloud' || options.nebulaType === 'dark' ? 1.0 : 0.0 },
        uRing: { value: options.nebulaType === 'planetary' || options.nebulaType === 'supernova_remnant' ? 1.0 : 0.0 },
        uAnomaly: { value: options.objectType === 'anomaly_region' ? 1.0 : 0.0 },
        uReflection: { value: options.nebulaType === 'reflection' ? 1.0 : 0.0 },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform sampler2D uNoise;
        uniform sampler2D uMask;
        uniform vec3 uColorA;
        uniform vec3 uColorB;
        uniform vec3 uColorC;
        uniform float uOpacity;
        uniform float uEmissionStrength;
        uniform float uTime;
        uniform float uDark;
        uniform float uRing;
        uniform float uAnomaly;
        uniform float uReflection;
        varying vec2 vUv;

        float levelRange(float value, float minInput, float maxInput) {
          return clamp((value - minInput) / (maxInput - minInput), 0.0, 1.0);
        }

        void main() {
          vec2 centered = vUv - vec2(0.5);
          float radius = length(centered);
          float ovalMask = smoothstep(0.52, 0.16, radius);
          float ringMask = smoothstep(0.50, 0.36, radius) * smoothstep(0.18, 0.30, radius);
          float shapeMask = mix(ovalMask, ringMask, uRing);

          vec2 driftA = vec2(uTime * 0.010, -uTime * 0.014);
          vec2 driftB = vec2(-uTime * 0.006, uTime * 0.008 + 0.21);
          float n1 = texture2D(uNoise, vUv * 1.35 + driftA).r;
          float n2 = texture2D(uNoise, vUv * 2.20 + driftB).r;
          float maskNoise = texture2D(uMask, vUv + centered * (0.18 + n1 * 0.16)).r;
          float cloud = levelRange((n1 + n2 + maskNoise) * 0.38, 0.22, 0.72);
          float edge = smoothstep(0.58, 0.08, radius + (n2 - 0.5) * 0.16);
          float ringFill = mix(1.0, smoothstep(0.20, 0.04, abs(radius - 0.32)), uRing * 0.35);
          float alpha = cloud * shapeMask * edge * ringFill * uOpacity;

          float blendAB = clamp(n1 * 0.7 + n2 * 0.45, 0.0, 1.0);
          float blendBC = clamp(maskNoise * 0.9 + n2 * 0.3, 0.0, 1.0);
          vec3 color = mix(uColorA, uColorB, blendAB);
          color = mix(color, uColorC, blendBC * 0.55);
          color = mix(color, vec3(0.03, 0.05, 0.09), uDark * 0.68);
          color += vec3(0.20, 0.05, 0.35) * uAnomaly * n2;
          float glowMask = pow(clamp(cloud * 0.82 + maskNoise * 0.48, 0.0, 1.0), 1.55);
          vec3 glowColor = mix(uColorB, uColorC, 0.45 + uAnomaly * 0.15);
          float glowStrength = mix(uEmissionStrength * 0.55, uEmissionStrength, uReflection);
          color += glowColor * glowMask * glowStrength;
          gl_FragColor = vec4(color, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: options.objectType === 'dust_cloud' || options.nebulaType === 'dark' ? THREE.NormalBlending : THREE.AdditiveBlending,
    })
    cloudMaterials.push(material)
    return material
  }

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

  const createLodPoint = (position: THREE.Vector3, colorValue = 0xffffff, size = 2.2) => {
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([position.x, position.y, position.z], 3))
    const point = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({
        color: colorValue,
        size,
        transparent: true,
        opacity: 0.86,
        sizeAttenuation: false,
        depthWrite: false,
      })
    )
    point.visible = false
    scene.add(point)
    return point
  }

  for (const system of props.payload.systems) {
    const isFarObjective = system.object_role === 'far_objective'
    const isWaypoint = system.object_role === 'navigation_waypoint'
    const baseMaterial = system.has_life ? lifeMaterial : systemMaterial
    const material = isWaypoint
      ? waypointMaterial
      : isFarObjective
        ? farObjectiveMaterial
        : texturedStandardMaterial(system.visual_data?.texture_key, baseMaterial)
    if (material instanceof THREE.MeshStandardMaterial && system.visual_data?.emissive) {
      material.emissive = new THREE.Color(system.visual_data.emissive)
    }
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
    const point = createLodPoint(mesh.position, isWaypoint || isFarObjective ? 0xffffff : 0xf8fbff, isFarObjective || system.id === targetId ? 3.0 : 2.2)
    point.userData.label = mesh.userData.label
    selectable.push(point as unknown as Selectable)
    lodEntries.push({
      mesh,
      ring,
      point,
      near: isWaypoint ? 135 : isFarObjective ? 180 : 150,
      far: isFarObjective || system.id === targetId ? 1400 : 780,
      keepVisible: system.id === targetId || isFarObjective,
    })
  }

  for (const body of props.payload.bodies) {
    const bodyMaterial = texturedStandardMaterial(body.visual_data?.texture_key, bodyFallbackMaterial(body))
    if (body.visual_data?.emissive) {
      bodyMaterial.emissive = new THREE.Color(body.visual_data.emissive)
    }
    if (typeof body.visual_data?.roughness === 'number') {
      bodyMaterial.roughness = body.visual_data.roughness
    }
    if (body.type === 'star') {
      bodyMaterial.emissiveIntensity = body.visual_data?.emission_strength ?? 1.25
    }
    const visualRadius = bodyVisualRadius(body)
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(visualRadius, 24, 16), bodyMaterial)
    mesh.position.set(body.x, body.y, body.z)
    mesh.userData.label = `${body.name} / ${body.type}`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
    if (body.visual_data?.ring) {
      const ringVisual = body.visual_data.ring
      const ringTexture = loadTexture(pickTextureSet(ringVisual.texture_key)?.alpha ?? pickTextureSet(ringVisual.texture_key)?.albedo)
      const ringMaterial = new THREE.MeshBasicMaterial({
        color: ringVisual.color ?? '#d9d1b0',
        map: ringTexture,
        transparent: true,
        opacity: ringVisual.opacity ?? 0.7,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(
          (ringVisual.inner_radius ?? 1.5) * visualRadius,
          (ringVisual.outer_radius ?? 2.3) * visualRadius,
          72,
        ),
        ringMaterial,
      )
      ring.position.copy(mesh.position)
      ring.rotation.set(Math.PI / 2 + (ringVisual.tilt ?? 0), 0, 0.22)
      scene.add(ring)
      lodEntries.push({ mesh: ring, point: createLodPoint(mesh.position, lodColorForBody(body), 1.8), near: 110, far: 260 })
    }
    const point = createLodPoint(mesh.position, lodColorForBody(body), 1.8)
    point.userData.label = mesh.userData.label
    selectable.push(point as unknown as Selectable)
    lodEntries.push({ mesh, point, near: body.object_role === 'origin_body' ? 95 : 82, far: 280 })
  }

  for (const signal of props.payload.signals) {
    const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(signal.investigated ? 0.16 : 0.24), signalMaterial)
    mesh.position.set(signal.x, signal.y, signal.z)
    mesh.userData.label = `${signal.id} / ${signal.kind}`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
    const point = createLodPoint(mesh.position, 0xffdbe6, signal.investigated ? 1.1 : 1.4)
    point.userData.label = mesh.userData.label
    selectable.push(point as unknown as Selectable)
    lodEntries.push({ mesh, point, near: 90, far: 260 })
  }

  for (const item of props.payload.environment_objects ?? []) {
    const textureSet = pickTextureSet(item.visual_data?.texture_key)
    const noise = loadTexture(textureSet?.noise ?? textureSet?.albedo ?? textureSet?.emission)
    const mask = loadTexture(textureSet?.alpha ?? textureSet?.noise)
    const details = item.details ?? {}
    const colorProfile = Array.isArray(details.color_profile) ? details.color_profile : item.visual_data?.color_profile
    const colorValue = typeof colorProfile?.[0] === 'string' ? colorProfile[0] : item.object_type === 'anomaly_region' ? '#c084fc' : '#8fd3ff'
    const colorValueB = typeof colorProfile?.[1] === 'string' ? colorProfile[1] : item.object_type === 'dust_cloud' ? '#172033' : '#f8fafc'
    const colorValueC = typeof colorProfile?.[2] === 'string' ? colorProfile[2] : item.object_type === 'anomaly_region' ? '#f8fafc' : '#fff4cc'
    const opacity = item.visual_data?.opacity ?? (typeof details.opacity === 'number' ? details.opacity : item.object_type === 'dust_cloud' ? 0.18 : 0.28)
    const emissionStrength =
      item.visual_data?.emission_strength ??
      (typeof details.emission_strength === 'number' ? details.emission_strength : item.object_type === 'dust_cloud' ? 0.12 : 0.9)
    const nebulaType = typeof details.nebula_type === 'string' ? details.nebula_type : item.nebula_type
    const material = createCloudMaterial({
      noise,
      mask,
      colorA: new THREE.Color(colorValue),
      colorB: new THREE.Color(colorValueB),
      colorC: new THREE.Color(colorValueC),
      opacity,
      emissionStrength,
      nebulaType,
      objectType: item.object_type,
    })
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1, 16, 16), material)
    mesh.position.set(item.x, item.y, item.z)
    mesh.scale.set(item.scale.x, item.scale.y, item.scale.z)
    mesh.rotation.set(item.rotation.x, item.rotation.y, item.rotation.z)
    mesh.userData.label = `${item.name} / ${item.object_type}`
    scene.add(mesh)
    cloudMeshes.push(mesh)
    selectable.push(mesh as unknown as Selectable)
  }

  const probeLength = probeVisualLength(props.payload)
  const probe = new THREE.Mesh(new THREE.ConeGeometry(probeLength * 0.34, probeLength, 4), probeMaterial)
  const probeVisualOffset = new THREE.Vector3(probeLength * 1.4, probeLength * 2.3, probeLength * 1.1)
  const probeMotion = useProbeMotion(props.payload)
  const probeCurrentAnchor = probeMotion.renderedPosition
  probe.position.copy(probeCurrentAnchor.clone().add(probeVisualOffset))
  probe.userData.label = props.payload.probe.name
  scene.add(probe)
  selectable.push(probe as unknown as Selectable)

  const probeMarker = new THREE.Mesh(
    new THREE.RingGeometry(0.52, 0.58, 40),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.86, side: THREE.DoubleSide })
  )
  probeMarker.position.copy(probeCurrentAnchor)
  probeMarker.rotation.x = Math.PI / 2
  scene.add(probeMarker)

  const origin = props.payload.map_origin
  let originLine: THREE.Line | null = null
  let routeLine: THREE.Line | null = null
  let dynamicRouteLine: THREE.Line | null = null
  let predictionLine: THREE.Line | null = null
  let primaryPredictionLine: THREE.Line | null = null
  if (origin) {
    const originPoint = vectorFrom(origin)
    originLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([originPoint, probeCurrentAnchor.clone()]),
      new THREE.LineBasicMaterial({ color: 0xa7c8ff, transparent: true, opacity: 0.32 })
    )
    scene.add(originLine)
  }

  const disposeObjectMaterial = (object: THREE.Object3D) => {
    const material = (object as THREE.Line).material
    if (Array.isArray(material)) material.forEach((item) => item.dispose())
    else material.dispose()
  }
  const removeLine = (line: THREE.Line | null) => {
    if (!line) return null
    scene.remove(line)
    line.geometry.dispose()
    disposeObjectMaterial(line)
    return null
  }
  const routeGeometry = () => {
    const points = props.payload.route.slice(0, -1).map((point) => new THREE.Vector3(point.x, point.y, point.z))
    const routePoints = points.length >= 4 ? new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.35).getPoints(points.length * 10) : points
    return new THREE.BufferGeometry().setFromPoints(routePoints)
  }
  const lastConfirmedRoutePoint = () => {
    const fixedRoute = props.payload.route.slice(0, -1)
    const point = fixedRoute.at(-1) ?? props.payload.route[0]
    return point ? new THREE.Vector3(point.x, point.y, point.z) : probeCurrentAnchor.clone()
  }
  const syncRouteLine = () => {
    if (props.payload.route.length < 3) {
      routeLine = removeLine(routeLine)
    } else {
      const geometry = routeGeometry()
      if (!routeLine) {
        routeLine = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x9fffe6, transparent: true, opacity: 0.72 }))
        scene.add(routeLine)
      } else {
        routeLine.geometry.dispose()
        routeLine.geometry = geometry
      }
    }
    const dynamicGeometry = new THREE.BufferGeometry().setFromPoints([lastConfirmedRoutePoint(), probeCurrentAnchor.clone()])
    if (!dynamicRouteLine) {
      dynamicRouteLine = new THREE.Line(dynamicGeometry, new THREE.LineBasicMaterial({ color: 0x9fffe6, transparent: true, opacity: 0.96 }))
      scene.add(dynamicRouteLine)
      return
    }
    dynamicRouteLine.geometry.dispose()
    dynamicRouteLine.geometry = dynamicGeometry
  }
  const updateDynamicRouteLine = () => {
    if (!dynamicRouteLine) return
    const positions = dynamicRouteLine.geometry.getAttribute('position') as THREE.BufferAttribute
    const start = lastConfirmedRoutePoint()
    positions.setXYZ(0, start.x, start.y, start.z)
    positions.setXYZ(1, probeCurrentAnchor.x, probeCurrentAnchor.y, probeCurrentAnchor.z)
    positions.needsUpdate = true
    dynamicRouteLine.geometry.computeBoundingSphere()
  }
  const syncPredictionLine = (
    current: THREE.Line | null,
    prediction: MapPayload['route_prediction'],
    options: { color: number; opacity: number; dashSize: number; gapSize: number },
  ) => {
    if (!prediction) return removeLine(current)
    const geometry = new THREE.BufferGeometry().setFromPoints([probeCurrentAnchor.clone(), vectorFrom(prediction.to)])
    if (!current) {
      const line = new THREE.Line(
        geometry,
        new THREE.LineDashedMaterial({ color: options.color, transparent: true, opacity: options.opacity, dashSize: options.dashSize, gapSize: options.gapSize })
      )
      line.computeLineDistances()
      scene.add(line)
      return line
    }
    current.geometry.dispose()
    current.geometry = geometry
    current.computeLineDistances()
    return current
  }
  const syncPredictionLines = () => {
    predictionLine = syncPredictionLine(predictionLine, props.payload.route_prediction, { color: 0xdbeafe, opacity: 0.42, dashSize: 2.2, gapSize: 1.5 })
    primaryPredictionLine = syncPredictionLine(primaryPredictionLine, props.payload.primary_route_prediction, { color: 0xf8fbff, opacity: 0.22, dashSize: 7.0, gapSize: 4.0 })
  }
  syncRouteLine()
  syncPredictionLines()

  const raycaster = new THREE.Raycaster()
  raycaster.params.Points = { threshold: 4 }
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

  const stopProbeWatch = watch(
    () => [
      props.payload.probe.navigation?.display_position?.x ?? props.payload.probe.x,
      props.payload.probe.navigation?.display_position?.y ?? props.payload.probe.y,
      props.payload.probe.navigation?.display_position?.z ?? props.payload.probe.z,
      props.payload.probe.navigation?.sampled_at ?? '',
      props.payload.probe.navigation?.phase ?? '',
      props.payload.probe.navigation?.progress ?? 0,
      props.payload.probe.target_id,
    ] as const,
    () => {
      retargetProbe()
    },
    { flush: 'sync' },
  )
  const stopRouteWatch = watch(
    () => props.payload.route.map((point) => `${point.x}:${point.y}:${point.z}`).join('|'),
    syncRouteLine,
    { flush: 'sync' },
  )
  const stopPredictionWatch = watch(
    () => [
      props.payload.route_prediction?.target_id ?? '',
      props.payload.route_prediction?.from.x ?? 0,
      props.payload.route_prediction?.from.y ?? 0,
      props.payload.route_prediction?.from.z ?? 0,
      props.payload.route_prediction?.to.x ?? 0,
      props.payload.route_prediction?.to.y ?? 0,
      props.payload.route_prediction?.to.z ?? 0,
      props.payload.primary_route_prediction?.target_id ?? '',
      props.payload.primary_route_prediction?.from.x ?? 0,
      props.payload.primary_route_prediction?.from.y ?? 0,
      props.payload.primary_route_prediction?.from.z ?? 0,
      props.payload.primary_route_prediction?.to.x ?? 0,
      props.payload.primary_route_prediction?.to.y ?? 0,
      props.payload.primary_route_prediction?.to.z ?? 0,
    ].join(':'),
    syncPredictionLines,
    { flush: 'sync' },
  )

  localFollowEnabled.value = false
  const followCamera = useProbeFollowCamera(camera, controls, probeCurrentAnchor)
  setProbeFollow = (enabled: boolean) => {
    if (followCamera.isEnabled() === enabled) return
    localFollowEnabled.value = enabled
    if (enabled) selected.value = props.payload.probe.name
    followCamera.setEnabled(enabled, probeCurrentAnchor)
  }
  if (props.followEnabled) setProbeFollow(true)

  let frame = 0
  let lastFrameAt = performance.now()
  const effectiveTimeScale = () => (props.paused || props.payload.clock?.clock_state === 'paused' ? 0 : props.payload.clock?.time_scale ?? 1)
  const isMotionPaused = () => Boolean(props.paused) || props.payload.clock?.clock_state === 'paused' || effectiveTimeScale() === 0
  const retargetProbe = () => {
    probeMotion.updateSnapshot(props.payload)
  }
  const stopClockWatch = watch(
    () => [props.payload.clock?.time_scale ?? 1, props.payload.clock?.clock_state ?? 'running', Boolean(props.paused)] as const,
    () => {
      if (isMotionPaused()) {
        probeMotion.pauseMotion()
        return
      }
      probeMotion.resumeMotion(effectiveTimeScale())
    },
    { flush: 'sync', immediate: true },
  )
  const animate = () => {
    frame = requestAnimationFrame(animate)
    const now = performance.now()
    const deltaSeconds = Math.min(0.08, (now - lastFrameAt) / 1000)
    lastFrameAt = now
    const motionPaused = isMotionPaused()
    if (!motionPaused) probeMotion.updateFrame(deltaSeconds, now)
    probe.position.copy(probeCurrentAnchor).add(probeVisualOffset)
    probeMarker.position.copy(probeCurrentAnchor)
    if (!motionPaused) {
      probe.rotation.y += 0.014
      probeMarker.rotation.z += 0.01
      updateDynamicRouteLine()
      if (predictionLine || primaryPredictionLine) syncPredictionLines()
      if (originLine) {
        const positions = originLine.geometry.getAttribute('position') as THREE.BufferAttribute
        positions.setXYZ(1, probeCurrentAnchor.x, probeCurrentAnchor.y, probeCurrentAnchor.z)
        positions.needsUpdate = true
        originLine.geometry.computeBoundingSphere()
      }
    }
    const time = performance.now() * 0.001
    for (const material of cloudMaterials) material.uniforms.uTime.value = time
    for (const mesh of cloudMeshes) mesh.lookAt(camera.position)
    if (!motionPaused) followCamera.update(probeCurrentAnchor)
    const distance = camera.position.distanceTo(controls.target)
    starPoints.visible = distance > 8
    for (const entry of lodEntries) {
      const objectDistance = camera.position.distanceTo(entry.mesh.position)
      const isNear = objectDistance <= entry.near
      const isTooFar = objectDistance > entry.far && !entry.keepVisible
      entry.mesh.visible = isNear && !isTooFar
      entry.point.visible = !isNear && !isTooFar
      if (entry.ring) entry.ring.visible = isNear && !isTooFar
    }
    controls.update()
    renderer.render(scene, camera)
  }
  animate()

  cleanup = () => {
    cameraViewStore().__spaceMapCameraView = {
      compact: Boolean(props.compact),
      offset: camera.position.clone().sub(controls.target),
      targetDeltaFromProbe: controls.target.clone().sub(probeCurrentAnchor),
    }
    cancelAnimationFrame(frame)
    stopProbeWatch()
    stopClockWatch()
    stopRouteWatch()
    stopPredictionWatch()
    renderer.domElement.removeEventListener('click', click)
    window.removeEventListener('resize', resize)
    renderer.dispose()
    starGeometry.dispose()
    for (const entry of lodEntries) {
      entry.point.geometry.dispose()
      const material = entry.point.material
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material.dispose()
    }
    removeLine(routeLine)
    removeLine(dynamicRouteLine)
    removeLine(predictionLine)
    removeLine(primaryPredictionLine)
    host.value?.replaceChildren()
    setProbeFollow = null
  }
})

watch(() => props.followTick, () => setProbeFollow?.(!localFollowEnabled.value))
watch(() => props.followEnabled, (enabled) => {
  if (typeof enabled === 'boolean') setProbeFollow?.(enabled)
})
onBeforeUnmount(() => cleanup?.())
</script>

<template>
  <div>
    <div ref="host" class="map-frame" :class="{ 'map-compact': compact }" />
    <div v-if="!hideToolbar" class="map-toolbar">
      <button type="button" :class="{ 'is-active': localFollowEnabled }" @click="setProbeFollow?.(!localFollowEnabled)">
        {{ localFollowEnabled ? '追尾解除' : '探査機を追尾' }}
      </button>
      <span class="map-chip">選択: {{ selected }}</span>
      <span class="map-legend map-legend--star">恒星系</span>
      <span class="map-legend map-legend--waypoint">航行点</span>
      <span class="map-legend map-legend--planet">天体</span>
      <span class="map-legend map-legend--signal">信号</span>
      <span class="map-chip">航行: {{ payload.navigation_intent ?? 'main_route' }}</span>
    </div>
  </div>
</template>
