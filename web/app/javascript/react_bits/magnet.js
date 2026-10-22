const ROOT_CLASS = "magnet"
const INNER_CLASS = "magnet__inner"
const ACTIVE_ATTRIBUTE = "data-magnet-active"
const MAX_STEP_SECONDS = 1 / 30
const SOLVER_STEP_SECONDS = 1 / 120
const TILT_PERSPECTIVE = 800

const DEFAULT_SPRING = { stiffness: 170, damping: 16, mass: 1 }

const DEFAULTS = {
  padding: 100,
  disabled: false,
  magnetStrength: 2,
  maxOffset: undefined,
  exclusive: true,
  axis: "both",
  tilt: 0,
  scale: 1,
  spring: undefined,
  onActiveChange: undefined
}

const registry = new Set()
const field = { pointer: null, owner: null }
let detach = null

const smoothstep = (edge0, edge1, value) => {
  const t = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

const reach = (rect, pointer) => {
  const dx = pointer.x - (rect.left + rect.width / 2)
  const dy = pointer.y - (rect.top + rect.height / 2)
  const outside = Math.hypot(Math.max(0, Math.abs(dx) - rect.width / 2), Math.max(0, Math.abs(dy) - rect.height / 2))
  return { dx, dy, outside }
}

const arbitrate = () => {
  let winner = null
  let nearest = Infinity
  let closest = Infinity
  for (const entry of registry) {
    const s = entry.magnet.settings
    let near = null
    if (field.pointer && entry.visible && !s.disabled && !entry.magnet.reduced) {
      near = reach(entry.magnet.element.getBoundingClientRect(), field.pointer)
      if (near.outside > s.padding) near = null
    }
    if (!s.exclusive) {
      if (near || entry.magnet.engaged) entry.magnet.wake()
      continue
    }
    if (!near) continue
    const center = Math.hypot(near.dx, near.dy)
    if (near.outside < nearest || (near.outside === nearest && center < closest)) {
      winner = entry
      nearest = near.outside
      closest = center
    }
  }
  const previous = field.owner
  field.owner = winner
  if (previous && previous !== winner) previous.magnet.wake()
  if (winner) winner.magnet.wake()
}

const attach = () => {
  const onPointerMove = (event) => {
    if (event.pointerType === "touch") return
    field.pointer = { x: event.clientX, y: event.clientY }
    arbitrate()
  }
  const onLeave = () => {
    field.pointer = null
    arbitrate()
  }
  window.addEventListener("pointermove", onPointerMove, { passive: true })
  window.addEventListener("scroll", arbitrate, { passive: true, capture: true })
  document.documentElement.addEventListener("pointerleave", onLeave)
  window.addEventListener("blur", onLeave)
  return () => {
    window.removeEventListener("pointermove", onPointerMove)
    window.removeEventListener("scroll", arbitrate, { capture: true })
    document.documentElement.removeEventListener("pointerleave", onLeave)
    window.removeEventListener("blur", onLeave)
  }
}

const resolve = (options) => ({
  padding: Math.max(0, options.padding),
  disabled: options.disabled,
  strength: Math.max(0.1, options.magnetStrength),
  maxOffset: options.maxOffset,
  exclusive: options.exclusive,
  axis: options.axis,
  tilt: options.tilt,
  scale: options.scale,
  stiffness: Math.max(1, options.spring?.stiffness ?? DEFAULT_SPRING.stiffness),
  damping: Math.max(0, options.spring?.damping ?? DEFAULT_SPRING.damping),
  mass: Math.max(0.01, options.spring?.mass ?? DEFAULT_SPRING.mass),
  onActiveChange: options.onActiveChange
})

export default class Magnet {
  constructor(element, options = {}) {
    this.element = element
    this.options = { ...DEFAULTS, ...options }
    this.settings = resolve(this.options)
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    this.current = { x: 0, y: 0, tiltX: 0, tiltY: 0, scale: 1 }
    this.velocity = { x: 0, y: 0, tiltX: 0, tiltY: 0, scale: 0 }
    this.engaged = false
    this.raf = 0
    this.last = 0
    this.alive = true
    this.addedClass = !element.classList.contains(ROOT_CLASS)

    this.frame = this.frame.bind(this)

    this.inner = document.createElement("div")
    this.inner.className = INNER_CLASS
    this.inner.style.willChange = "transform"
    this.inner.append(...element.childNodes)
    element.append(this.inner)
    element.classList.add(ROOT_CLASS)

    this.entry = { magnet: this, visible: true }
    this.intersection = new IntersectionObserver((entries) => {
      this.entry.visible = entries.some((entry) => entry.isIntersecting)
      if (!this.entry.visible) arbitrate()
    })
    this.intersection.observe(element)
    registry.add(this.entry)
    if (!detach) detach = attach()
    this.wakeAll()
  }

  update(options = {}) {
    if (!this.alive) return
    this.options = { ...this.options, ...options }
    this.settings = resolve(this.options)
    this.wakeAll()
  }

  destroy() {
    if (!this.alive) return
    this.alive = false
    cancelAnimationFrame(this.raf)
    this.raf = 0
    this.intersection.disconnect()
    registry.delete(this.entry)
    if (field.owner === this.entry) field.owner = null
    if (!registry.size && detach) {
      detach()
      detach = null
    }
    this.element.removeAttribute(ACTIVE_ATTRIBUTE)
    this.element.append(...this.inner.childNodes)
    this.inner.remove()
    if (this.addedClass) this.element.classList.remove(ROOT_CLASS)
    if (!this.element.classList.length) this.element.removeAttribute("class")
  }

  wakeAll() {
    arbitrate()
    this.wake()
  }

  wake() {
    if (!this.raf && this.alive) this.raf = requestAnimationFrame(this.frame)
  }

  solve(target, dt) {
    const s = this.settings
    const current = this.current
    const velocity = this.velocity
    let resting = true
    Object.keys(current).forEach((key) => {
      const force = s.stiffness * (target[key] - current[key]) - s.damping * velocity[key]
      velocity[key] += (force / s.mass) * dt
      current[key] += velocity[key] * dt
      const epsilon = key === "scale" ? 0.001 : 0.05
      if (Math.abs(target[key] - current[key]) > epsilon || Math.abs(velocity[key]) > epsilon) resting = false
    })
    return resting
  }

  measure() {
    const s = this.settings
    const target = { x: 0, y: 0, tiltX: 0, tiltY: 0, scale: 1 }
    if (s.disabled || this.reduced || !field.pointer || !this.entry.visible) return { target, engaged: false }
    if (s.exclusive && field.owner !== this.entry) return { target, engaged: false }
    const rect = this.element.getBoundingClientRect()
    const { dx, dy, outside } = reach(rect, field.pointer)
    if (outside > s.padding) return { target, engaged: false }
    const pull = s.padding > 0 ? 1 - smoothstep(s.padding * 0.5, s.padding, outside) : 1
    let x = s.axis === "y" ? 0 : (dx / s.strength) * pull
    let y = s.axis === "x" ? 0 : (dy / s.strength) * pull
    if (s.maxOffset !== undefined && s.maxOffset !== null) {
      const length = Math.hypot(x, y)
      if (length > s.maxOffset) {
        x *= s.maxOffset / length
        y *= s.maxOffset / length
      }
    }
    const nx = Math.max(-1, Math.min(1, dx / Math.max(rect.width / 2, 1)))
    const ny = Math.max(-1, Math.min(1, dy / Math.max(rect.height / 2, 1)))
    target.x = x
    target.y = y
    target.tiltX = -ny * s.tilt * pull
    target.tiltY = nx * s.tilt * pull
    target.scale = 1 + (s.scale - 1) * pull
    return { target, engaged: true }
  }

  apply() {
    const { x, y, tiltX, tiltY, scale } = this.current
    const turned = Math.abs(tiltX) > 0.01 || Math.abs(tiltY) > 0.01
    const tilt = turned
      ? ` perspective(${TILT_PERSPECTIVE}px) rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg)`
      : ""
    const zoom = Math.abs(scale - 1) > 0.0005 ? ` scale(${scale.toFixed(4)})` : ""
    this.inner.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)${tilt}${zoom}`
  }

  frame(now) {
    this.raf = 0
    if (!this.alive) return
    const dt = this.last ? Math.min((now - this.last) / 1000, MAX_STEP_SECONDS) : 1 / 60
    this.last = now
    const { target, engaged } = this.measure()
    if (engaged !== this.engaged) {
      this.engaged = engaged
      if (engaged) this.element.setAttribute(ACTIVE_ATTRIBUTE, "")
      else this.element.removeAttribute(ACTIVE_ATTRIBUTE)
      this.settings.onActiveChange?.(engaged)
    }
    const steps = Math.ceil(dt / SOLVER_STEP_SECONDS)
    let resting = true
    for (let i = 0; i < steps; i++) resting = this.solve(target, dt / steps)
    if (resting) {
      Object.keys(this.current).forEach((key) => {
        this.current[key] = target[key]
        this.velocity[key] = 0
      })
    }
    this.apply()
    if (!resting) this.raf = requestAnimationFrame(this.frame)
    else this.last = 0
  }
}
