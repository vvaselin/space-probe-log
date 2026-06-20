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
  showTargetCallout?: boolean
}>()
const selected = ref<string>('未選択')
const localFollowEnabled = ref(false)
const host = ref<HTMLDivElement | null>(null)
const targetCallout = ref<HTMLDivElement | null>(null)
let cleanup: (() => void) | null = null
let setProbeFollow: ((enabled: boolean) => void) | null = null

const targetCalloutData = computed(() => {
  const navigation = props.payload.probe.navigation
  const prediction = props.payload.route_prediction
  const name = navigation?.destination_name ?? prediction?.target_name
  if (!name) return null
  return {
    name,
    distance: navigation ? `${navigation.remaining_distance_pc.toFixed(4)} pc` : '-',
    eta: navigation?.eta_datetime ? navigation.eta_datetime.replace('T', ' ').slice(0, 10) : '-',
    progress: navigation ? `${Math.round(navigation.progress_percent)}%` : '-',
  }
})
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

function seededRandom(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6D2B79F5) >>> 0
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function spectralColor(spectralType?: string | null) {
  const spectralClass = spectralType?.trim().toUpperCase().charAt(0) ?? 'G'
  return {
    O: '#9bbcff',
    B: '#aabfff',
    A: '#cad7ff',
    F: '#f8f7ff',
    G: '#fff4d6',
    K: '#ffd2a1',
    M: '#ff9a6b',
  }[spectralClass] ?? '#fff4d6'
}

function emissiveColor(value: unknown, spectralType?: string | null) {
  return new THREE.Color(typeof value === 'string' ? value : spectralColor(spectralType))
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
  renderer.toneMappingExposure = 1.15
  host.value.appendChild(renderer.domElement)

  scene.add(new THREE.AmbientLight(0xb8c8e6, 0.035))

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
  const rockyMaterial = new THREE.MeshStandardMaterial({ color: 0xb8a58d, roughness: 0.96, metalness: 0 })
  const earthMaterial = new THREE.MeshStandardMaterial({ color: 0x5fa8ff, roughness: 0.92, metalness: 0 })
  const gasMaterial = new THREE.MeshStandardMaterial({ color: 0x9fc4ff, roughness: 0.94, metalness: 0 })
  const iceMaterial = new THREE.MeshStandardMaterial({ color: 0xbad9ff, roughness: 0.9, metalness: 0 })
  const moonMaterial = new THREE.MeshStandardMaterial({ color: 0xb7b2ab, roughness: 1, metalness: 0 })
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
    const selfLuminous = textureKey?.startsWith('lava_') ?? false
    const emissionMap = selfLuminous ? loadTexture(textureSet?.emission) : undefined
    if (!map && !roughnessMap && !emissionMap) return fallback
    return new THREE.MeshStandardMaterial({
      color: fallback.color,
      emissive: selfLuminous ? 0x5a1608 : 0x000000,
      roughness: Math.max(0.9, fallback.roughness),
      metalness: 0,
      map,
      roughnessMap,
      emissiveMap: emissionMap,
      emissiveIntensity: emissionMap ? 0.65 : 0,
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
    if (body.type === 'star') return emissiveColor(body.visual_data?.emissive, body.spectral_type)
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

  const distantStars = props.payload.distant_stars ?? []
  const starPoints = new THREE.Group()
  const starGeometries: THREE.BufferGeometry[] = []
  const starPointMaterials: THREE.PointsMaterial[] = []
  const addDistantStarLayer = (
    stars: typeof distantStars,
    textureUrl: string | undefined,
    size: number,
    opacity: number,
  ) => {
    const positions: number[] = []
    const colors: number[] = []
    const color = new THREE.Color()
    for (const star of stars) {
      positions.push(star.x, star.y, star.z)
      color.set(star.color)
      colors.push(color.r * star.brightness, color.g * star.brightness, color.b * star.brightness)
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
    const material = new THREE.PointsMaterial({
      map: loadTexture(textureUrl),
      size,
      vertexColors: true,
      transparent: true,
      opacity,
      alphaTest: 0.06,
      sizeAttenuation: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      toneMapped: false,
    })
    starGeometries.push(geometry)
    starPointMaterials.push(material)
    starPoints.add(new THREE.Points(geometry, material))
  }
  addDistantStarLayer(
    distantStars.filter((star) => star.brightness < 1.35),
    pickTextureSet('star_yellow_01')?.albedo,
    5,
    0.82,
  )
  addDistantStarLayer(
    distantStars.filter((star) => star.brightness >= 1.35),
    pickTextureSet('star_blue_01')?.albedo,
    10,
    0.95,
  )
  scene.add(starPoints)

  const smallBodyGeometries: THREE.BufferGeometry[] = []
  const smallBodyMaterials: THREE.Material[] = []
  const particleTexture = loadTexture(pickTextureSet('star_blue_01')?.emission)
  for (const layer of props.payload.small_body_layers ?? []) {
    const random = seededRandom(layer.seed)
    const positions: number[] = []
    const center = vectorFrom(layer.center)
    if (layer.layer_type === 'asteroid_belt') {
      for (let index = 0; index < layer.particle_count; index += 1) {
        const angle = random() * Math.PI * 2
        const radius = Math.sqrt(layer.inner_radius ** 2 + random() * (layer.outer_radius ** 2 - layer.inner_radius ** 2))
        positions.push(
          center.x + Math.cos(angle) * radius,
          center.y + (random() - 0.5) * layer.thickness,
          center.z + Math.sin(angle) * radius,
        )
      }
    } else if (layer.layer_type === 'oort_cloud') {
      for (let index = 0; index < layer.particle_count; index += 1) {
        const azimuth = random() * Math.PI * 2
        const cosPolar = random() * 2 - 1
        const sinPolar = Math.sqrt(1 - cosPolar * cosPolar)
        const radius = Math.cbrt(layer.inner_radius ** 3 + random() * (layer.outer_radius ** 3 - layer.inner_radius ** 3))
        positions.push(
          center.x + Math.cos(azimuth) * sinPolar * radius,
          center.y + cosPolar * radius,
          center.z + Math.sin(azimuth) * sinPolar * radius,
        )
      }
    } else if (layer.layer_type === 'comet_population') {
      const tailPositions: number[] = []
      for (let index = 0; index < layer.particle_count; index += 1) {
        const angle = random() * Math.PI * 2
        const radius = layer.inner_radius + (layer.outer_radius - layer.inner_radius) * random() ** 1.8
        const position = new THREE.Vector3(
          center.x + Math.cos(angle) * radius,
          center.y + (random() - 0.5) * layer.thickness,
          center.z + Math.sin(angle) * radius,
        )
        positions.push(position.x, position.y, position.z)
        const tailDirection = position.clone().sub(center).normalize()
        const tailEnd = position.clone().addScaledVector(tailDirection, 1.4 + random() * 1.8)
        tailPositions.push(position.x, position.y, position.z, tailEnd.x, tailEnd.y, tailEnd.z)
      }
      const tailGeometry = new THREE.BufferGeometry()
      tailGeometry.setAttribute('position', new THREE.Float32BufferAttribute(tailPositions, 3))
      const tailMaterial = new THREE.LineBasicMaterial({
        color: layer.visual_data?.tail_color ?? '#8fdcff',
        transparent: true,
        opacity: (layer.visual_data?.opacity ?? 0.78) * 0.72,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      const tails = new THREE.LineSegments(tailGeometry, tailMaterial)
      tails.userData.label = layer.name
      scene.add(tails)
      smallBodyGeometries.push(tailGeometry)
      smallBodyMaterials.push(tailMaterial)
    } else {
      continue
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    const material = new THREE.PointsMaterial({
      color: layer.visual_data?.color ?? '#cbd5e1',
      map: particleTexture,
      size: (layer.visual_data?.point_size ?? 0.06) * 18,
      transparent: true,
      opacity: layer.visual_data?.opacity ?? 0.4,
      alphaTest: 0.04,
      sizeAttenuation: false,
      depthWrite: false,
      blending: layer.layer_type === 'asteroid_belt' ? THREE.NormalBlending : THREE.AdditiveBlending,
      toneMapped: false,
    })
    const points = new THREE.Points(geometry, material)
    points.userData.label = layer.name
    scene.add(points)
    selectable.push(points as unknown as Selectable)
    smallBodyGeometries.push(geometry)
    smallBodyMaterials.push(material)
  }

  const createLodPoint = (position: THREE.Vector3, colorValue: THREE.ColorRepresentation = 0xffffff, size = 2.2) => {
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

  const createDownwardSquarePyramidGeometry = (halfWidth: number, height: number) => {
    const halfHeight = height / 2
    const apex = [0, -halfHeight, 0]
    const corners = [
      [-halfWidth, halfHeight, -halfWidth],
      [halfWidth, halfHeight, -halfWidth],
      [halfWidth, halfHeight, halfWidth],
      [-halfWidth, halfHeight, halfWidth],
    ]
    const positions: number[] = []
    const addTriangle = (left: number[], middle: number[], right: number[]) => positions.push(...left, ...middle, ...right)
    for (let index = 0; index < corners.length; index += 1) {
      addTriangle(apex, corners[index], corners[(index + 1) % corners.length])
    }
    addTriangle(corners[0], corners[2], corners[1])
    addTriangle(corners[0], corners[3], corners[2])
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geometry.computeVertexNormals()
    return geometry
  }

  type StellarLightCandidate = { position: THREE.Vector3; color: THREE.Color; emissionStrength: number }
  const stellarCandidates: StellarLightCandidate[] = []
  const stellarMaterials: THREE.MeshBasicMaterial[] = []
  const createStellarMaterial = (colorValue: THREE.Color) => {
    const material = new THREE.MeshBasicMaterial({ color: colorValue, toneMapped: false })
    stellarMaterials.push(material)
    return material
  }
  const registerStellarLight = (position: THREE.Vector3, colorValue: THREE.Color, emissionStrength: number) => {
    stellarCandidates.push({ position: position.clone(), color: colorValue.clone(), emissionStrength })
  }
  const stellarLightPool = Array.from({ length: 4 }, () => {
    const light = new THREE.PointLight(0xffffff, 0, 220, 2)
    scene.add(light)
    return light
  })
  const lastLightTarget = new THREE.Vector3(Number.POSITIVE_INFINITY, 0, 0)
  const updateStellarLights = (force = false) => {
    if (!force && lastLightTarget.distanceToSquared(controls.target) < 0.25) return
    lastLightTarget.copy(controls.target)
    const nearest = [...stellarCandidates]
      .sort((left, right) => left.position.distanceToSquared(controls.target) - right.position.distanceToSquared(controls.target))
      .slice(0, stellarLightPool.length)
    stellarLightPool.forEach((light, index) => {
      const candidate = nearest[index]
      if (!candidate) {
        light.intensity = 0
        return
      }
      light.position.copy(candidate.position)
      light.color.copy(candidate.color)
      light.intensity = clamp(candidate.emissionStrength * 900, 650, 1800)
      light.distance = clamp(220 + candidate.emissionStrength * 80, 280, 460)
    })
  }

  const systemsWithStellarBodies = new Set(
    props.payload.bodies.filter((body) => body.type === 'star').map((body) => body.system_id),
  )

  for (const system of props.payload.systems) {
    const isFarObjective = system.object_role === 'far_objective'
    const isWaypoint = system.object_role === 'navigation_waypoint'
    const starColor = emissiveColor(system.visual_data?.emissive, system.spectral_type)
    const emissionStrength = system.visual_data?.emission_strength ?? 1.25
    const material = isWaypoint
      ? waypointMaterial
      : isFarObjective
        ? farObjectiveMaterial
        : createStellarMaterial(starColor)
    const radius = isWaypoint ? 0.72 : isFarObjective ? 1.8 : system.id === 'sol' ? 1.45 : 1.05
    const geometry = isWaypoint ? new THREE.OctahedronGeometry(radius, 0) : new THREE.SphereGeometry(radius, 32, 20)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.set(system.x, system.y, system.z)
    mesh.userData.label = `${system.name} (${system.id})`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
    if (!isWaypoint && !isFarObjective && !systemsWithStellarBodies.has(system.id)) {
      registerStellarLight(mesh.position, starColor, emissionStrength)
    }

    const ringColor = isWaypoint ? 0xdbeafe : isFarObjective ? 0xffffff : system.has_life ? 0x6df2b2 : starColor
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius + 0.45, radius + 0.6, 64),
      new THREE.MeshBasicMaterial({ color: ringColor, transparent: true, opacity: isWaypoint ? 0.45 : isFarObjective ? 0.62 : 0.3, side: THREE.DoubleSide })
    )
    ring.position.copy(mesh.position)
    ring.rotation.x = Math.PI / 2
    scene.add(ring)
    const point = createLodPoint(mesh.position, isWaypoint || isFarObjective ? 0xffffff : starColor, isFarObjective || system.id === targetId ? 3.0 : 2.2)
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

  const renderedBodies = new Map<string, { position: THREE.Vector3; radius: number }>()
  for (const body of props.payload.bodies) {
    const bodyStarColor = emissiveColor(body.visual_data?.emissive, body.spectral_type)
    const bodyMaterial = body.type === 'star'
      ? createStellarMaterial(bodyStarColor)
      : texturedStandardMaterial(body.visual_data?.texture_key, bodyFallbackMaterial(body))
    if (typeof body.visual_data?.roughness === 'number' && bodyMaterial instanceof THREE.MeshStandardMaterial) {
      bodyMaterial.roughness = Math.max(0.88, body.visual_data.roughness)
    }
    const visualRadius = bodyVisualRadius(body)
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(visualRadius, 24, 16), bodyMaterial)
    mesh.position.set(body.x, body.y, body.z)
    renderedBodies.set(body.id, { position: mesh.position.clone(), radius: visualRadius })
    mesh.userData.label = `${body.name} / ${body.type}`
    scene.add(mesh)
    selectable.push(mesh as unknown as Selectable)
    if (body.type === 'star') {
      registerStellarLight(mesh.position, bodyStarColor, body.visual_data?.emission_strength ?? 1.25)
    }
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
    const markerHeight = signal.investigated ? 0.28 : 0.4
    const markerHalfWidth = signal.investigated ? 0.14 : 0.2
    const mesh = new THREE.Mesh(createDownwardSquarePyramidGeometry(markerHalfWidth, markerHeight), signalMaterial)
    const linkedBody = signal.body_id ? renderedBodies.get(signal.body_id) : undefined
    if (linkedBody) {
      const surfaceGap = Math.max(0.06, linkedBody.radius * 0.04)
      mesh.position.copy(linkedBody.position)
      mesh.position.y += linkedBody.radius + surfaceGap + markerHeight / 2
    } else {
      mesh.position.set(signal.x, signal.y, signal.z)
    }
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
  const probeMotion = useProbeMotion(props.payload)
  const probeCurrentAnchor = probeMotion.renderedPosition
  probe.position.copy(probeCurrentAnchor)
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
  const segmentProgress = (point: THREE.Vector3, origin: THREE.Vector3, destination: THREE.Vector3) => {
    const segment = destination.clone().sub(origin)
    const lengthSq = segment.lengthSq()
    if (lengthSq <= 1e-9) return 1
    return point.clone().sub(origin).dot(segment) / lengthSq
  }
  const confirmedTrailPoints = () => {
    const points = props.payload.route.slice(0, -1).map((point) => new THREE.Vector3(point.x, point.y, point.z))
    const navigation = props.payload.probe.navigation
    if (!navigation?.active || !navigation.origin_display_position || !navigation.destination_display_position || !points.length) return points

    const origin = vectorFrom(navigation.origin_display_position)
    const destination = vectorFrom(navigation.destination_display_position)
    const renderedProgress = segmentProgress(probeCurrentAnchor, origin, destination)
    let originIndex = 0
    let nearestOriginDistance = Number.POSITIVE_INFINITY
    points.forEach((point, index) => {
      const distance = point.distanceToSquared(origin)
      if (distance <= nearestOriginDistance) {
        nearestOriginDistance = distance
        originIndex = index
      }
    })
    return [
      ...points.slice(0, originIndex + 1),
      ...points.slice(originIndex + 1).filter((point) => segmentProgress(point, origin, destination) <= renderedProgress + 1e-6),
    ]
  }
  const routeGeometry = (points = confirmedTrailPoints()) => {
    const routePoints = points.length >= 4 ? new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.35).getPoints(points.length * 10) : points
    return new THREE.BufferGeometry().setFromPoints(routePoints)
  }
  const lastConfirmedRoutePoint = () => {
    return confirmedTrailPoints().at(-1) ?? probeCurrentAnchor.clone()
  }
  const syncRouteLine = () => {
    const confirmedPoints = confirmedTrailPoints()
    if (confirmedPoints.length < 2) {
      routeLine = removeLine(routeLine)
    } else {
      const geometry = routeGeometry(confirmedPoints)
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
    const previousStart = new THREE.Vector3(positions.getX(0), positions.getY(0), positions.getZ(0))
    if (previousStart.distanceToSquared(start) > 1e-9) {
      syncRouteLine()
      return
    }
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
    const nextWidth = host.value.clientWidth
    const nextHeight = host.value.clientHeight
    if (nextWidth <= 0 || nextHeight <= 0) return
    camera.aspect = nextWidth / nextHeight
    camera.updateProjectionMatrix()
    renderer.setSize(nextWidth, nextHeight)
  }
  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(host.value)
  window.addEventListener('resize', resize)
  resize()

  const updateTargetCallout = () => {
    const element = targetCallout.value
    const destination = props.payload.probe.navigation?.destination_display_position ?? props.payload.route_prediction?.to
    if (!element || !props.showTargetCallout || !destination || !host.value) return
    const projected = vectorFrom(destination).project(camera)
    const x = (projected.x * 0.5 + 0.5) * host.value.clientWidth
    const y = (-projected.y * 0.5 + 0.5) * host.value.clientHeight
    const visible = projected.z >= -1 && projected.z <= 1
    element.hidden = !visible
    if (!visible) return
    element.style.transform = `translate3d(${x}px, ${y}px, 0)`
  }

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
    probe.position.copy(probeCurrentAnchor)
    probeMarker.position.copy(probeCurrentAnchor)
    if (!motionPaused) {
      probe.rotation.y += 0.014
      probeMarker.rotation.z += 0.01
      updateDynamicRouteLine()
      if (predictionLine) syncPredictionLines()
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
    controls.update()
    followCamera.update(probeCurrentAnchor)
    for (const entry of lodEntries) {
      const objectDistance = camera.position.distanceTo(entry.mesh.position)
      const isNear = objectDistance <= entry.near
      const isTooFar = objectDistance > entry.far && !entry.keepVisible
      entry.mesh.visible = isNear && !isTooFar
      entry.point.visible = !isNear && !isTooFar
      if (entry.ring) entry.ring.visible = isNear && !isTooFar
    }
    updateStellarLights()
    updateTargetCallout()
    renderer.render(scene, camera)
  }
  updateStellarLights(true)
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
    resizeObserver.disconnect()
    controls.dispose()
    for (const light of stellarLightPool) scene.remove(light)
    for (const material of stellarMaterials) material.dispose()
    for (const texture of textureCache.values()) texture.dispose()
    for (const material of cloudMaterials) material.dispose()
    renderer.dispose()
    for (const geometry of starGeometries) geometry.dispose()
    for (const material of starPointMaterials) material.dispose()
    for (const geometry of smallBodyGeometries) geometry.dispose()
    for (const material of smallBodyMaterials) material.dispose()
    for (const entry of lodEntries) {
      entry.point.geometry.dispose()
      const material = entry.point.material
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material.dispose()
    }
    removeLine(routeLine)
    removeLine(dynamicRouteLine)
    removeLine(predictionLine)
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
  <div class="space-map-shell">
    <div ref="host" class="map-frame" :class="{ 'map-compact': compact }" />
    <div v-if="showTargetCallout && targetCalloutData" ref="targetCallout" class="target-callout" hidden>
      <span class="target-callout__marker" />
      <span class="target-callout__leader" />
      <div class="target-callout__body">
        <strong>{{ targetCalloutData.name }}</strong>
        <dl>
          <dt>DIST</dt><dd>{{ targetCalloutData.distance }}</dd>
          <dt>ETA</dt><dd>{{ targetCalloutData.eta }}</dd>
          <dt>PROG</dt><dd>{{ targetCalloutData.progress }}</dd>
        </dl>
      </div>
    </div>
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
