const ROOT_CLASS = "spotlight-card"
const LIGHT_CLASS = "spotlight-card--light"
const MAX_FRAME_SECONDS = 0.05
const AMBIENT_CEILING = 0.6
const FALLOFF_STOPS = 14
const GRAIN_SIZE = 160

const DEFAULTS = {
  spotlightColor: undefined,
  intensity: 0.15,
  spotlightSize: 240,
  softness: 0.7,
  shape: "circle",
  borderGlow: 0.6,
  proximity: 80,
  smoothing: 0.3,
  ambient: false,
  flare: true,
  grain: 0,
  theme: "dark"
}

const THEMES = {
  dark: { light: "#ffffff", fill: 1, edge: 1 },
  light: { light: "#18181b", fill: 0.28, edge: 0.7 }
}

const SHAPES = ["circle", "beam"]

const NOISE = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='${GRAIN_SIZE}' height='${GRAIN_SIZE}'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

const falloff = (color, softness) => {
  const soft = clamp(softness, 0, 1)
  const core = (1 - soft) ** 1.5 * 0.85
  const stop = (alpha, at) =>
    `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(2)}%, transparent) ${(at * 100).toFixed(2)}%`
  const list = [stop(1, 0)]
  for (let i = 0; i <= FALLOFF_STOPS; i++) {
    const t = core + ((1 - core) * i) / FALLOFF_STOPS
    const g = (t - core) / (1 - core)
    const smooth = 1 - g * g * (3 - 2 * g)
    const glow = Math.exp(-4.6 * g * g) * (1 - g ** 6)
    list.push(stop(smooth + (glow - smooth) * soft, t))
  }
  return list.join(", ")
}

const resolve = (options) => {
  const palette = THEMES[options.theme] ?? THEMES.dark
  const color = options.spotlightColor ?? palette.light
  return {
    light: options.theme === "light",
    shape: SHAPES.includes(options.shape) ? options.shape : "circle",
    fill: falloff(color, options.softness),
    edge: falloff(color, 1),
    size: Math.max(20, options.spotlightSize),
    intensity: clamp(options.intensity, 0, 1) * palette.fill,
    borderGlow: clamp(options.borderGlow, 0, 1) * palette.edge,
    proximity: Math.max(0, options.proximity),
    smoothing: clamp(options.smoothing, 0, 1),
    ambient: options.ambient,
    flare: options.flare,
    grain: clamp(options.grain, 0, 1)
  }
}

const layer = (className) => {
  const node = document.createElement("span")
  node.className = className
  node.setAttribute("aria-hidden", "true")
  return node
}

export default class SpotlightCard {
  constructor(element, options = {}) {
    this.element = element
    this.options = { ...DEFAULTS, ...options }
    this.settings = resolve(this.options)
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    this.state = {
      x: 0,
      y: 0,
      presence: 0,
      flare: 0,
      time: Math.random() * 60,
      pressed: false,
      visible: true
    }
    this.pointer = { x: 0, y: 0, active: false }
    this.drawn = { light: "", edge: "", noise: "", grainImage: false }
    this.focus = null
    this.raf = 0
    this.last = 0
    this.alive = true
    this.pageVisible = !document.hidden
    this.addedClass = !element.classList.contains(ROOT_CLASS)

    this.tick = this.tick.bind(this)
    this.onMove = this.onMove.bind(this)
    this.onOut = this.onOut.bind(this)
    this.onDown = this.onDown.bind(this)
    this.onUp = this.onUp.bind(this)
    this.onFocusIn = this.onFocusIn.bind(this)
    this.onFocusOut = this.onFocusOut.bind(this)
    this.onScroll = this.onScroll.bind(this)
    this.onVisibility = this.onVisibility.bind(this)

    this.light = layer("spotlight-card__light")
    this.grain = layer("spotlight-card__grain")
    this.border = layer("spotlight-card__border")
    this.edge = layer("spotlight-card__edge")
    element.classList.add(ROOT_CLASS)
    element.classList.toggle(LIGHT_CLASS, this.settings.light)
    element.prepend(this.light, this.grain)
    element.append(this.border, this.edge)

    this.observer = new IntersectionObserver((entries) => {
      this.state.visible = entries.some((entry) => entry.isIntersecting)
      if (this.state.visible) this.wake()
    })
    this.observer.observe(element)
    window.addEventListener("pointermove", this.onMove)
    window.addEventListener("pointerup", this.onUp)
    window.addEventListener("pointercancel", this.onUp)
    window.addEventListener("scroll", this.onScroll, { capture: true, passive: true })
    document.addEventListener("pointerout", this.onOut)
    document.addEventListener("visibilitychange", this.onVisibility)
    element.addEventListener("pointerdown", this.onDown)
    element.addEventListener("focusin", this.onFocusIn)
    element.addEventListener("focusout", this.onFocusOut)
    this.wake()
  }

  update(options = {}) {
    if (!this.alive) return
    this.options = { ...this.options, ...options }
    this.settings = resolve(this.options)
    this.element.classList.toggle(LIGHT_CLASS, this.settings.light)
    this.drawn.light = ""
    this.drawn.edge = ""
    this.drawn.noise = ""
    this.wake()
  }

  destroy() {
    if (!this.alive) return
    this.alive = false
    cancelAnimationFrame(this.raf)
    this.raf = 0
    this.observer.disconnect()
    window.removeEventListener("pointermove", this.onMove)
    window.removeEventListener("pointerup", this.onUp)
    window.removeEventListener("pointercancel", this.onUp)
    window.removeEventListener("scroll", this.onScroll, { capture: true })
    document.removeEventListener("pointerout", this.onOut)
    document.removeEventListener("visibilitychange", this.onVisibility)
    this.element.removeEventListener("pointerdown", this.onDown)
    this.element.removeEventListener("focusin", this.onFocusIn)
    this.element.removeEventListener("focusout", this.onFocusOut)
    this.light.remove()
    this.grain.remove()
    this.border.remove()
    this.edge.remove()
    this.element.classList.remove(LIGHT_CLASS)
    if (this.addedClass) this.element.classList.remove(ROOT_CLASS)
    if (!this.element.classList.length) this.element.removeAttribute("class")
  }

  gradient(s, size, x, y, stops) {
    if (s.shape === "beam") {
      const reach = Math.max(size * 0.6, y + size * 0.55)
      return `radial-gradient(${(size * 0.55).toFixed(1)}px ${reach.toFixed(1)}px at ${x.toFixed(1)}px 0px, ${stops})`
    }
    return `radial-gradient(circle ${size.toFixed(1)}px at ${x.toFixed(1)}px ${y.toFixed(1)}px, ${stops})`
  }

  paint(s) {
    const state = this.state
    const drawn = this.drawn
    const size = s.size * (1 + 0.2 * state.flare)
    const boost = 1 + 0.7 * state.flare
    const fill = this.gradient(s, size, state.x, state.y, s.fill)
    const rim = this.gradient(s, size * 0.6, state.x, s.shape === "beam" ? 0 : state.y, s.edge)
    if (fill !== drawn.light) {
      drawn.light = fill
      this.light.style.background = fill
    }
    if (rim !== drawn.edge) {
      drawn.edge = rim
      this.edge.style.background = rim
    }
    this.light.style.opacity = String(Math.min(1, state.presence * s.intensity * boost))
    this.edge.style.opacity = String(Math.min(1, state.presence * s.borderGlow * boost))
    if (s.grain > 0 !== drawn.grainImage) {
      drawn.grainImage = s.grain > 0
      this.grain.style.backgroundImage = drawn.grainImage ? NOISE : ""
      this.grain.style.backgroundSize = drawn.grainImage ? `${GRAIN_SIZE}px ${GRAIN_SIZE}px` : ""
    }
    const grainy = s.grain > 0 ? this.gradient(s, size, state.x, state.y, "#000 0%, transparent 100%") : "none"
    if (grainy !== drawn.noise) {
      drawn.noise = grainy
      this.grain.style.webkitMaskImage = grainy
      this.grain.style.maskImage = grainy
    }
    this.grain.style.opacity = String(state.presence * s.grain)
  }

  tick(now) {
    this.raf = 0
    if (!this.alive) return
    const s = this.settings
    const state = this.state
    const pointer = this.pointer
    const dt = Math.min(MAX_FRAME_SECONDS, Math.max(0.001, (now - this.last) / 1000))
    this.last = now
    const rect = this.element.getBoundingClientRect()
    let tx = state.x
    let ty = state.y
    let target = 0
    if (this.focus && this.element.contains(this.focus)) {
      const box = this.focus.getBoundingClientRect()
      tx = box.left + box.width / 2 - rect.left
      ty = box.top + box.height / 2 - rect.top
      target = 1
    } else if (pointer.active) {
      tx = pointer.x - rect.left
      ty = pointer.y - rect.top
      const gap = Math.hypot(Math.max(0, -tx, tx - rect.width), Math.max(0, -ty, ty - rect.height))
      if (gap === 0) target = 1
      else if (s.proximity > 0) target = Math.max(0, 1 - gap / s.proximity) ** 2
    }
    if (target < AMBIENT_CEILING && s.ambient && state.visible) {
      if (!this.reduced) state.time += dt
      const drift = AMBIENT_CEILING - target
      tx += (rect.width * (0.5 + 0.34 * Math.sin(state.time * 0.43)) - tx) * (drift / AMBIENT_CEILING)
      ty += (rect.height * (0.5 + 0.3 * Math.sin(state.time * 0.61 + 1.3)) - ty) * (drift / AMBIENT_CEILING)
      target = AMBIENT_CEILING
    }
    if (state.presence < 0.02 && target > 0 && !s.ambient) {
      state.x = tx
      state.y = ty
    }
    const follow = this.reduced || s.smoothing === 0 ? 1 : 1 - Math.exp(-dt / (0.015 + s.smoothing * 0.22))
    state.x += (tx - state.x) * follow
    state.y += (ty - state.y) * follow
    const fade = this.reduced ? 1 : 1 - Math.exp(-dt / (target > state.presence ? 0.1 : 0.32))
    state.presence += (target - state.presence) * fade
    if (Math.abs(target - state.presence) < 0.002) state.presence = target
    const press = state.pressed && s.flare && !this.reduced ? 1 : 0
    state.flare += (press - state.flare) * (1 - Math.exp(-dt / (press ? 0.05 : 0.28)))
    if (Math.abs(press - state.flare) < 0.002) state.flare = press
    this.paint(s)
    const moving = Math.abs(tx - state.x) > 0.1 || Math.abs(ty - state.y) > 0.1
    const settled = !moving && state.presence === target && state.flare === press
    const drifting = s.ambient && state.visible && !this.reduced
    if ((!settled || drifting) && this.pageVisible) this.raf = requestAnimationFrame(this.tick)
  }

  wake() {
    if (this.raf || !this.alive || !this.pageVisible) return
    this.last = performance.now()
    this.raf = requestAnimationFrame(this.tick)
  }

  onMove(event) {
    const pointer = this.pointer
    pointer.x = event.clientX
    pointer.y = event.clientY
    pointer.active = true
    if (this.state.presence > 0 || this.settings.proximity > 0 || this.element.contains(event.target)) this.wake()
  }

  onOut(event) {
    if (event.relatedTarget) return
    this.pointer.active = false
    this.wake()
  }

  onDown(event) {
    const pointer = this.pointer
    pointer.x = event.clientX
    pointer.y = event.clientY
    pointer.active = true
    this.state.pressed = true
    this.wake()
  }

  onUp(event) {
    if (event.pointerType !== "mouse") this.pointer.active = false
    if (!this.state.pressed && event.pointerType === "mouse") return
    this.state.pressed = false
    this.wake()
  }

  onFocusIn(event) {
    if (!(event.target instanceof Element) || !event.target.matches(":focus-visible")) return
    this.focus = event.target
    this.wake()
  }

  onFocusOut(event) {
    if (this.element.contains(event.relatedTarget)) return
    this.focus = null
    this.wake()
  }

  onScroll() {
    if (this.pointer.active || this.state.presence > 0) this.wake()
  }

  onVisibility() {
    this.pageVisible = !document.hidden
    this.wake()
  }
}
