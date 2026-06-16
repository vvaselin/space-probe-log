import fbmNoise from './texture_FbmNoise_512px.png?url'
import fractalCamo from './texture_FractalCamo_512px.png?url'
import glare from './texture_Glare_512px.png?url'
import grunge from './texture_Grunge_512px.png?url'
import lava from './texture_Lava_512px.png?url'
import plasma from './texture_PlasmaV2_512px.png?url'
import ripple from './texture_Ripple_512px.png?url'
import solarGlow from './texture_SolarGlow_512px.png?url'

export type TextureSet = {
  albedo?: string
  normal?: string
  roughness?: string
  emission?: string
  alpha?: string
  noise?: string
}

export const textureRegistry: Record<string, TextureSet> = {
  rocky_01: { albedo: fractalCamo, roughness: grunge },
  cloudy_01: { albedo: lava, roughness: fbmNoise },
  ice_01: { albedo: fbmNoise, roughness: grunge },
  ocean_01: { albedo: lava, emission: glare },
  lava_01: { albedo: lava, emission: plasma },
  gas_blue_01: { albedo: plasma, emission: glare },
  moon_01: { albedo: grunge, roughness: grunge },
  asteroid_01: { albedo: grunge, roughness: grunge },
  ring_01: { albedo: fbmNoise, alpha: grunge },
  star_yellow_01: { albedo: solarGlow, emission: glare },
  star_red_01: { albedo: solarGlow, emission: glare },
  star_blue_01: { albedo: glare, emission: glare },
  star_giant_01: { albedo: solarGlow, emission: glare },
  nebula_fbm_01: { noise: fbmNoise, alpha: grunge, emission: fbmNoise },
  dust_grunge_01: { noise: grunge, alpha: grunge, emission: fbmNoise },
  anomaly_plasma_01: { noise: ripple, alpha: fbmNoise, emission: plasma },
}

export function pickTextureSet(textureKey?: string | null): TextureSet | undefined {
  if (!textureKey) return undefined
  return textureRegistry[textureKey]
}
