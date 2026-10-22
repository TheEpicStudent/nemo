const PIXEL_BUDGET = 2.4e6
const MAX_PULSES = 4
const INTRO_SECONDS = 1.8
const MAX_FRAME_SECONDS = 0.05
const STEER_SECONDS = 0.2
const SHADE_GLIDE_SECONDS = 0.08
const SHADE_IN_SECONDS = 0.25
const SHADE_OUT_SECONDS = 0.5
const PULSE_SECONDS = 2
const PULSE_RISE_SECONDS = 0.15
const SHADOW_WIDTH = 16
const MIN_RATIO = 0.5
const MAX_RATIO = 3
const ROOT_CLASS = "light-rays"
const CANVAS_CLASS = "light-rays__canvas"

const CANVAS_STYLE = {
  position: "absolute",
  inset: "0",
  display: "block",
  width: "100%",
  height: "100%",
  pointerEvents: "none"
}

const CONTEXT_ATTRIBUTES = {
  alpha: true,
  premultipliedAlpha: true,
  antialias: false,
  depth: false,
  stencil: false,
  powerPreference: "high-performance"
}

const DEFAULTS = {
  raysOrigin: "top-center",
  raysColor: "#ffffff",
  raysSpeed: 1,
  lightSpread: 0.5,
  rayLength: 3,
  rayDensity: 1,
  tilt: 0,
  raySharpness: 0.35,
  glow: 0.6,
  haze: 0.25,
  atmosphere: 1,
  intensity: 1,
  pulsating: false,
  fadeDistance: 1,
  saturation: 1,
  followMouse: true,
  mouseInfluence: 0.1,
  cursorShadow: true,
  clickPulse: true,
  noiseAmount: 0,
  distortion: 0,
  intro: true,
  lightMode: false,
  opacity: 1,
  maxDevicePixelRatio: 2
}

const ORIGINS = {
  "top-left": { anchor: [0, -0.2], dir: [0, 1] },
  "top-center": { anchor: [0.5, -0.2], dir: [0, 1] },
  "top-right": { anchor: [1, -0.2], dir: [0, 1] },
  left: { anchor: [-0.2, 0.5], dir: [1, 0] },
  right: { anchor: [1.2, 0.5], dir: [-1, 0] },
  "bottom-left": { anchor: [0, 1.2], dir: [0, -1] },
  "bottom-center": { anchor: [0.5, 1.2], dir: [0, -1] },
  "bottom-right": { anchor: [1, 1.2], dir: [0, -1] }
}

const VERTEX = `#version 300 es
const vec2 corners[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() {
  gl_Position = vec4(corners[gl_VertexID], 0.0, 1.0);
}`

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uResolution;
uniform float uScale;
uniform float uTime;
uniform vec2 uSource;
uniform vec2 uAim;
uniform float uReach;
uniform vec3 uColor;
uniform float uSpread;
uniform float uLength;
uniform float uFade;
uniform float uSaturation;
uniform float uPulsating;
uniform float uNoise;
uniform float uDistortion;
uniform float uDensity;
uniform float uSharpness;
uniform float uGlow;
uniform float uHaze;
uniform float uAtmosphere;
uniform float uIntensity;
uniform vec4 uShadow;
uniform vec4 uPulses[${MAX_PULSES}];
uniform vec2 uIntro;
uniform float uLight;
uniform float uOpacity;
out vec4 fragColor;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = p - i;
  vec2 w = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), w.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), w.x), w.y);
}

float shape(float strength, float width) {
  float edge = max(mix(0.5, 0.08, uSharpness), width);
  return mix(strength, smoothstep(0.62 - edge, 0.62 + edge, strength), uSharpness);
}

void main() {
  vec2 coord = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y) / uScale;
  vec2 delta = coord - uSource;
  float distance = length(delta);
  vec2 dir = delta / max(distance, 1e-4);
  float cosAngle = dot(dir, uAim);
  float angle = cosAngle + uDistortion * sin(uTime * 2.0 + distance * 0.02) * 0.2;
  float slope = fwidth(angle);
  float depth = distance / uReach;

  float source = exp(-depth * depth * 9.0) * 0.9 + exp(-depth * 3.2) * 0.25;
  float glowLight = uGlow * source * smoothstep(-0.2, 0.6, cosAngle);
  float spread = pow(max(angle, 0.0), 1.0 / uSpread);
  float lengthFalloff = clamp(1.0 - distance / (uReach * uLength), 0.0, 1.0);
  float fadeFalloff = clamp(1.0 - distance / (uReach * uFade), 0.5, 1.0);
  float envelope = spread * lengthFalloff * fadeFalloff;
  float reveal = uIntensity * uIntro.y * (1.0 - smoothstep(uIntro.x - 0.35, uIntro.x, depth));
  if ((envelope * 1.6 + glowLight) * reveal < 0.0015) {
    fragColor = vec4(0.0);
    return;
  }

  float phaseA = angle * 36.2214 * uDensity + uTime * 1.5;
  float phaseB = -angle * 21.11349 * uDensity + uTime * 1.5;
  float phaseC = angle * 22.3991 * uDensity + uTime * 1.1;
  float phaseD = -angle * 18.0234 * uDensity + uTime * 1.1;
  float strengthA = clamp(0.75 + 0.15 * sin(phaseA) + 0.2 * cos(phaseB), 0.0, 1.0);
  float strengthB = clamp(0.75 + 0.15 * sin(phaseC) + 0.2 * cos(phaseD), 0.0, 1.0);
  float widthA = abs(0.15 * 36.2214 * cos(phaseA) + 0.2 * 21.11349 * sin(phaseB)) * uDensity * slope;
  float widthB = abs(0.15 * 22.3991 * cos(phaseC) + 0.2 * 18.0234 * sin(phaseD)) * uDensity * slope;
  float pulseA = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 4.5) : 1.0;
  float pulseB = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 3.3) : 1.0;
  float rayLight = envelope * (0.5 * shape(strengthA, widthA) * pulseA + 0.4 * shape(strengthB, widthB) * pulseB);

  if (uHaze > 0.0) {
    float around = atan(uAim.x * dir.y - uAim.y * dir.x, cosAngle);
    vec2 drift = vec2(around * 2.2 + uTime * 0.035, depth * 2.6 - uTime * 0.11);
    float fog = 0.65 * valueNoise(drift * vec2(3.0, 1.0)) + 0.35 * valueNoise(drift * vec2(7.0, 2.3) + 4.1);
    rayLight *= mix(1.0, 0.25 + 1.2 * fog, uHaze);
  }

  if (uShadow.z > 0.0) {
    vec2 toCursor = uShadow.xy - uSource;
    float cursorDistance = length(toCursor);
    float along = dot(delta, toCursor) / max(cursorDistance * cursorDistance, 1e-4);
    float side = abs(delta.x * toCursor.y - delta.y * toCursor.x) / max(cursorDistance, 1e-4);
    float trail = max(along - 1.0, 0.0);
    float width = uShadow.w * along + 0.22 * trail * cursorDistance;
    float behind = smoothstep(0.97, 1.25, along) * exp(-trail * 1.1);
    float shade = (1.0 - smoothstep(width * 0.3, width * 1.6, side)) * behind;
    rayLight *= 1.0 - uShadow.z * 0.62 * shade;
  }

  float boost = 0.0;
  for (int i = 0; i < ${MAX_PULSES}; i++) {
    vec4 wave = uPulses[i];
    if (wave.z <= 0.0) continue;
    float x = (depth - wave.x) / wave.y;
    boost += wave.z * exp(-x * x);
  }
  float light = (rayLight * (1.0 + boost) + glowLight) * reveal;

  if (uNoise > 0.0) {
    float n = fract(sin(dot(coord * 0.02 + uTime * 0.1, vec2(12.9898, 78.233))) * 43758.5453123);
    light *= 1.0 - uNoise + uNoise * n;
  }

  float near = clamp(1.2 - distance / (uResolution.y / uScale), 0.0, 1.0);
  vec3 tint = mix(vec3(0.9), vec3(0.1, 0.3, 0.5) + near * vec3(0.8, 0.6, 0.5), uAtmosphere);
  float gray = dot(tint, vec3(0.299, 0.587, 0.114));
  vec3 hue = max(mix(vec3(gray), tint, uSaturation), 0.0) * uColor;

  float grain = (fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5) / 255.0;
  if (uLight > 0.5) {
    vec3 color = hue * light;
    float energy = max(color.r, max(color.g, color.b));
    vec3 tone = clamp(1.0 - (1.0 - hue / max(max(hue.r, max(hue.g, hue.b)), 1e-4)) * 1.8, 0.0, 1.0);
    float warm = clamp((min(tone.r, tone.g) - tone.b) * 2.0, 0.0, 1.0);
    vec3 ink = tone * (mix(0.66, 0.94, warm) - 0.1 * smoothstep(0.4, 1.2, energy));
    float density = clamp(0.82 * (1.0 - exp(-1.5 * energy * energy)) * uOpacity + grain, 0.0, 1.0);
    fragColor = vec4(ink * density, density);
    return;
  }
  float level = light < 0.75 ? light : 0.75 + 0.25 * (1.0 - exp(-(light - 0.75) / 0.25));
  float top = max(hue.r, max(hue.g, hue.b));
  hue = mix(hue, vec3(top), smoothstep(0.8, 1.0, level) * 0.45);
  vec3 shown = clamp(hue * level, 0.0, 1.0) * level;
  fragColor = vec4(clamp(shown + grain, 0.0, level) * uOpacity, level * uOpacity);
}`

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

const parseColor = (value) => {
  const text = String(value || "").trim()
  const hex = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text)
  if (hex) {
    const full = hex[1].length === 3 ? hex[1].replace(/./g, (digit) => digit + digit) : hex[1]
    return [0, 2, 4].map((index) => parseInt(full.slice(index, index + 2), 16) / 255)
  }
  const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(text)
  if (rgb) return [rgb[1], rgb[2], rgb[3]].map((channel) => clamp(parseFloat(channel) / 255, 0, 1))
  return null
}

const compile = (gl, type, source) => {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(gl.getShaderInfoLog(shader))
    gl.deleteShader(shader)
    return null
  }
  return shader
}

const link = (gl) => {
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX)
  const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT)
  const program = vertex && fragment ? gl.createProgram() : null
  if (!vertex || !fragment || !program) {
    if (vertex) gl.deleteShader(vertex)
    if (fragment) gl.deleteShader(fragment)
    return null
  }
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  gl.deleteShader(vertex)
  gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(program))
    gl.deleteProgram(program)
    return null
  }
  const uniforms = {}
  const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS)
  for (let index = 0; index < count; index++) {
    const info = gl.getActiveUniform(program, index)
    if (info) uniforms[info.name.replace(/\[0\]$/, "")] = gl.getUniformLocation(program, info.name)
  }
  return { program, uniforms }
}

const smoother = (t) => {
  const x = clamp(t, 0, 1)
  return x * x * x * (x * (x * 6 - 15) + 10)
}

const resolve = (options) => ({
  origin: ORIGINS[options.raysOrigin] || ORIGINS["top-center"],
  color: parseColor(options.raysColor) || [1, 1, 1],
  speed: Math.max(0, options.raysSpeed),
  spread: Math.max(0.001, options.lightSpread),
  length: Math.max(0.01, options.rayLength),
  density: clamp(options.rayDensity, 0.1, 6),
  tilt: (clamp(options.tilt, -90, 90) * Math.PI) / 180,
  sharpness: clamp(options.raySharpness, 0, 1),
  glow: Math.max(0, options.glow),
  haze: clamp(options.haze, 0, 1),
  atmosphere: clamp(options.atmosphere, 0, 1),
  intensity: Math.max(0, options.intensity),
  pulsating: options.pulsating,
  fade: Math.max(0.01, options.fadeDistance),
  saturation: Math.max(0, options.saturation),
  follow: options.followMouse,
  influence: clamp(options.mouseInfluence, 0, 1),
  cursorShadow: options.cursorShadow,
  clickPulse: options.clickPulse,
  noise: clamp(options.noiseAmount, 0, 1),
  distortion: options.distortion,
  intro: options.intro,
  light: options.lightMode,
  opacity: clamp(options.opacity, 0, 1),
  maxRatio: clamp(options.maxDevicePixelRatio, MIN_RATIO, MAX_RATIO)
})

export default class LightRays {
  constructor(element, options = {}) {
    this.element = element
    this.options = { ...DEFAULTS, ...options }
    this.settings = resolve(this.options)
    this.canvas = document.createElement("canvas")
    this.gl = this.canvas.getContext("webgl2", CONTEXT_ATTRIBUTES)
    this.shader = this.gl ? link(this.gl) : null
    this.active = Boolean(this.shader)
    if (!this.active) return

    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    this.vao = this.gl.createVertexArray()
    this.size = { width: 1, height: 1, ratio: 1 }
    this.pointer = { x: 0.5, y: 0.5, inside: false, seen: false }
    this.aim = { x: 0.5, y: 0.5 }
    this.shade = { x: 0.5, y: 0.5, presence: 0 }
    this.pulses = []
    this.pulseData = new Float32Array(MAX_PULSES * 4)
    this.time = 0
    this.opening = this.settings.intro && !this.reduced ? 0 : 1
    this.raf = 0
    this.last = 0
    this.visible = true
    this.pageVisible = !document.hidden
    this.lost = false
    this.addedClass = !element.classList.contains(ROOT_CLASS)

    this.frame = this.frame.bind(this)
    this.onPointerMove = this.onPointerMove.bind(this)
    this.onPointerDown = this.onPointerDown.bind(this)
    this.onPointerUp = this.onPointerUp.bind(this)
    this.onLeave = this.onLeave.bind(this)
    this.onContextLost = this.onContextLost.bind(this)
    this.onContextRestored = this.onContextRestored.bind(this)
    this.onVisibility = this.onVisibility.bind(this)

    this.canvas.className = CANVAS_CLASS
    this.canvas.setAttribute("aria-hidden", "true")
    Object.assign(this.canvas.style, CANVAS_STYLE)
    element.classList.add(ROOT_CLASS)
    element.append(this.canvas)

    if (!this.reduced) {
      window.addEventListener("pointermove", this.onPointerMove, { passive: true })
      window.addEventListener("pointerdown", this.onPointerDown, { passive: true })
      window.addEventListener("pointerup", this.onPointerUp, { passive: true })
      window.addEventListener("pointercancel", this.onPointerUp, { passive: true })
      document.documentElement.addEventListener("pointerleave", this.onLeave)
    }
    this.canvas.addEventListener("webglcontextlost", this.onContextLost)
    this.canvas.addEventListener("webglcontextrestored", this.onContextRestored)
    document.addEventListener("visibilitychange", this.onVisibility)

    this.resizeObserver = new ResizeObserver(() => {
      this.resize()
      this.wake()
    })
    this.resizeObserver.observe(element)
    this.intersection = new IntersectionObserver((entries) => {
      this.visible = entries.some((entry) => entry.isIntersecting)
      this.wake()
    })
    this.intersection.observe(element)

    this.resize()
    this.wake()
  }

  update(options = {}) {
    if (!this.active) return
    this.options = { ...this.options, ...options }
    this.settings = resolve(this.options)
    this.resize()
    this.wake()
  }

  destroy() {
    if (!this.active) return
    this.active = false
    cancelAnimationFrame(this.raf)
    this.raf = 0
    this.resizeObserver.disconnect()
    this.intersection.disconnect()
    window.removeEventListener("pointermove", this.onPointerMove)
    window.removeEventListener("pointerdown", this.onPointerDown)
    window.removeEventListener("pointerup", this.onPointerUp)
    window.removeEventListener("pointercancel", this.onPointerUp)
    document.documentElement.removeEventListener("pointerleave", this.onLeave)
    document.removeEventListener("visibilitychange", this.onVisibility)
    this.canvas.removeEventListener("webglcontextlost", this.onContextLost)
    this.canvas.removeEventListener("webglcontextrestored", this.onContextRestored)
    if (!this.gl.isContextLost()) {
      this.gl.deleteVertexArray(this.vao)
      if (this.shader) this.gl.deleteProgram(this.shader.program)
      this.gl.getExtension("WEBGL_lose_context")?.loseContext()
    }
    this.canvas.remove()
    if (this.addedClass) this.element.classList.remove(ROOT_CLASS)
    if (!this.element.classList.length) this.element.removeAttribute("class")
  }

  resize() {
    const s = this.settings
    const rect = this.element.getBoundingClientRect()
    const cssWidth = Math.max(1, rect.width)
    const cssHeight = Math.max(1, rect.height)
    const detail = s.density * (0.35 + 0.65 * s.sharpness)
    const sampling = Math.max(clamp(0.35 + 0.3 * detail, 0.5, 2), s.noise > 0 ? 1 : 0)
    const ratio = Math.min(
      window.devicePixelRatio || 1,
      s.maxRatio,
      sampling,
      Math.sqrt(PIXEL_BUDGET / (cssWidth * cssHeight))
    )
    const width = Math.max(1, Math.round(cssWidth * ratio))
    const height = Math.max(1, Math.round(cssHeight * ratio))
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width
      this.canvas.height = height
    }
    this.size.width = cssWidth
    this.size.height = cssHeight
    this.size.ratio = width / cssWidth
  }

  wake() {
    if (this.raf || this.lost || !this.active || !this.visible || !this.pageVisible) return
    this.last = performance.now()
    this.raf = requestAnimationFrame(this.frame)
  }

  frame(now) {
    this.raf = 0
    if (this.lost || !this.active) return
    const s = this.settings
    const gl = this.gl
    const speed = this.reduced ? 0 : s.speed
    const follow = s.follow && !this.reduced
    const dt = clamp((now - this.last) / 1000 || 0, 0, MAX_FRAME_SECONDS)
    this.last = Math.max(this.last, now)
    this.time += dt * speed
    if (this.opening < 1) this.opening = Math.min(1, this.opening + dt / INTRO_SECONDS)

    const pointer = this.pointer
    const aim = this.aim
    const shade = this.shade
    const steer = 1 - Math.exp(-dt / STEER_SECONDS)
    const aimX = follow && pointer.seen ? pointer.x : 0.5
    const aimY = follow && pointer.seen ? pointer.y : 0.5
    aim.x += (aimX - aim.x) * steer
    aim.y += (aimY - aim.y) * steer
    const glide = 1 - Math.exp(-dt / SHADE_GLIDE_SECONDS)
    shade.x += (pointer.x - shade.x) * glide
    shade.y += (pointer.y - shade.y) * glide
    const shading = pointer.inside && s.cursorShadow && !this.reduced
    shade.presence +=
      ((shading ? 1 : 0) - shade.presence) * (1 - Math.exp(-dt / (shading ? SHADE_IN_SECONDS : SHADE_OUT_SECONDS)))

    for (let index = this.pulses.length - 1; index >= 0; index--) {
      this.pulses[index].age += dt
      if (this.pulses[index].age >= PULSE_SECONDS) this.pulses.splice(index, 1)
    }
    this.pulseData.fill(0)
    this.pulses.forEach((pulse, index) => {
      const t = pulse.age
      this.pulseData[index * 4] = 0.05 + t * 1.05
      this.pulseData[index * 4 + 1] = 0.14 + t * 0.14
      this.pulseData[index * 4 + 2] =
        0.9 * smoother(t / PULSE_RISE_SECONDS) * (1 - smoother(t / PULSE_SECONDS))
    })

    const width = this.size.width
    const height = this.size.height
    const sourceX = s.origin.anchor[0] * width
    const sourceY = s.origin.anchor[1] * height
    const cos = Math.cos(s.tilt)
    const sin = Math.sin(s.tilt)
    let dirX = s.origin.dir[0] * cos - s.origin.dir[1] * sin
    let dirY = s.origin.dir[0] * sin + s.origin.dir[1] * cos
    if (follow && s.influence > 0) {
      const mx = aim.x * width - sourceX
      const my = aim.y * height - sourceY
      const ml = Math.hypot(mx, my) || 1
      const bx = dirX + (mx / ml - dirX) * s.influence
      const by = dirY + (my / ml - dirY) * s.influence
      const bl = Math.hypot(bx, by) || 1
      dirX = bx / bl
      dirY = by / bl
    }
    const eased = 1 - Math.pow(1 - this.opening, 3)

    gl.viewport(0, 0, this.canvas.width, this.canvas.height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.useProgram(this.shader.program)
    gl.bindVertexArray(this.vao)
    const u = this.shader.uniforms
    gl.uniform2f(u.uResolution, this.canvas.width, this.canvas.height)
    gl.uniform1f(u.uScale, this.size.ratio)
    gl.uniform1f(u.uTime, this.time)
    gl.uniform2f(u.uSource, sourceX, sourceY)
    gl.uniform2f(u.uAim, dirX, dirY)
    gl.uniform1f(u.uReach, Math.max(width, height))
    gl.uniform3f(u.uColor, s.color[0], s.color[1], s.color[2])
    gl.uniform1f(u.uSpread, s.spread)
    gl.uniform1f(u.uLength, s.length)
    gl.uniform1f(u.uFade, s.fade)
    gl.uniform1f(u.uSaturation, s.saturation)
    gl.uniform1f(u.uPulsating, s.pulsating ? 1 : 0)
    gl.uniform1f(u.uNoise, s.noise)
    gl.uniform1f(u.uDistortion, s.distortion)
    gl.uniform1f(u.uDensity, s.density)
    gl.uniform1f(u.uSharpness, s.sharpness)
    gl.uniform1f(u.uGlow, s.glow)
    gl.uniform1f(u.uHaze, s.haze)
    gl.uniform1f(u.uAtmosphere, s.atmosphere)
    gl.uniform1f(u.uIntensity, s.intensity)
    gl.uniform4f(u.uShadow, shade.x * width, shade.y * height, shade.presence, SHADOW_WIDTH)
    gl.uniform4fv(u.uPulses, this.pulseData)
    gl.uniform2f(u.uIntro, eased * 2.6, smoother(this.opening / 0.5))
    gl.uniform1f(u.uLight, s.light ? 1 : 0)
    gl.uniform1f(u.uOpacity, s.opacity)
    gl.drawArrays(gl.TRIANGLES, 0, 3)

    const settling =
      Math.abs(aim.x - aimX) > 1e-4 ||
      Math.abs(aim.y - aimY) > 1e-4 ||
      (shade.presence > 1e-3 && Math.abs(shade.x - pointer.x) + Math.abs(shade.y - pointer.y) > 1e-4) ||
      Math.abs((shading ? 1 : 0) - shade.presence) > 1e-3 ||
      this.pulses.length > 0
    const busy = speed > 0 || this.opening < 1 || settling
    if (busy && this.visible && this.pageVisible) this.raf = requestAnimationFrame(this.frame)
  }

  locate(event) {
    const rect = this.element.getBoundingClientRect()
    return {
      x: (event.clientX - rect.left) / Math.max(1, rect.width),
      y: (event.clientY - rect.top) / Math.max(1, rect.height),
      inside:
        event.clientX >= rect.left &&
        event.clientX <= rect.right &&
        event.clientY >= rect.top &&
        event.clientY <= rect.bottom
    }
  }

  onPointerMove(event) {
    const spot = this.locate(event)
    if (!this.pointer.inside && spot.inside) {
      this.shade.x = spot.x
      this.shade.y = spot.y
    }
    this.pointer.x = spot.x
    this.pointer.y = spot.y
    this.pointer.inside = spot.inside
    this.pointer.seen = true
    this.wake()
  }

  onPointerDown(event) {
    const spot = this.locate(event)
    if (!spot.inside || !this.settings.clickPulse) return
    this.pulses.push({ age: 0 })
    if (this.pulses.length > MAX_PULSES) this.pulses.shift()
    this.wake()
  }

  onPointerUp(event) {
    if (event.pointerType !== "mouse") this.onLeave()
  }

  onLeave() {
    this.pointer.inside = false
    this.wake()
  }

  onVisibility() {
    this.pageVisible = !document.hidden
    this.wake()
  }

  onContextLost(event) {
    event.preventDefault()
    this.lost = true
    cancelAnimationFrame(this.raf)
    this.raf = 0
  }

  onContextRestored() {
    this.shader = link(this.gl)
    if (!this.shader) return
    this.vao = this.gl.createVertexArray()
    this.opening = 1
    this.lost = false
    this.resize()
    this.wake()
  }
}
