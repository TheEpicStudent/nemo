const CHAR_CLASS = "split-char"
const WORD_CLASS = "split-word"
const LINE_CLASS = "split-line"
const MASK_CLASS = "split-mask"
const DEFAULT_FROM = { opacity: 0, y: 40 }
const DEFAULT_TO = { opacity: 1, y: 0 }
const STIFFNESS = 180
const DAMPING = 19
const KICK = 0.024
const MILLISECONDS = 1000
const EASE_SAMPLES = 40
const ACCENT_DURATION_SCALE = 0.7
const ACCENT_DELAY_SCALE = 0.3
const EXIT_DURATION_SCALE = 0.55
const MIN_EXIT_DURATION = 0.35
const LINE_TOLERANCE = 0.6
const RESPLIT_DELAY = 120
const DEFAULT_OVERSHOOT = 1.7
const CSS_EASE_PATTERN = /^(cubic-bezier|steps\(|linear\(|ease|step-)/

const DEFAULTS = {
  text: undefined,
  delay: 50,
  duration: 1.25,
  ease: undefined,
  splitType: "chars",
  from: undefined,
  to: undefined,
  threshold: 0.1,
  rootMargin: "-100px",
  staggerFrom: "start",
  mask: false,
  effect: "rise",
  trigger: "view",
  loop: false,
  loopDelay: 1.5,
  hoverEffect: "none",
  accentColor: undefined,
  onLetterAnimationComplete: undefined
}

const POWERS = { power1: 2, power2: 3, power3: 4, power4: 5, quad: 2, cubic: 3, quart: 4, quint: 5 }

const EASE_IN = {
  sine: (t) => 1 - Math.cos((t * Math.PI) / 2),
  expo: (t) => (t === 0 ? 0 : 2 ** (10 * t - 10)),
  circ: (t) => 1 - Math.sqrt(1 - t * t),
  back: (t, overshoot) => t * t * ((overshoot + 1) * t - overshoot)
}

const TRANSFORM_KEYS = new Set([
  "x",
  "y",
  "xPercent",
  "yPercent",
  "scale",
  "scaleX",
  "scaleY",
  "rotation",
  "rotationX",
  "rotationY",
  "skewX",
  "skewY",
  "transformPerspective",
  "transformOrigin"
])

const NON_FRAME_KEYS = TRANSFORM_KEYS

const waveEase = (t) => 1 - Math.cos(t * Math.PI * 1.5) * Math.pow(1 - t, 1.2)

const parseEase = (spec) => {
  if (typeof spec === "function") return spec
  const match = /^(\w+)(?:\.(in|out|inOut))?(?:\(([^)]*)\))?$/.exec(String(spec).trim())
  if (!match) return null
  const [, name, type = "out", param] = match
  if (name === "none" || name === "linear") return (t) => t
  const overshoot = parseFloat(param) || DEFAULT_OVERSHOOT
  const base = POWERS[name] ? (t) => t ** POWERS[name] : EASE_IN[name]
  if (!base) return null
  const rise = (t) => base(t, overshoot)
  if (type === "in") return rise
  if (type === "out") return (t) => 1 - rise(1 - t)
  return (t) => (t < 0.5 ? rise(t * 2) / 2 : 1 - rise((1 - t) * 2) / 2)
}

const easeCache = new Map()

const cssEasing = (spec) => {
  if (typeof spec === "string" && CSS_EASE_PATTERN.test(spec)) return spec
  if (easeCache.has(spec)) return easeCache.get(spec)
  const curve = parseEase(spec)
  let easing = "ease-out"
  if (curve && CSS.supports("animation-timing-function", "linear(0, 1)")) {
    const points = Array.from({ length: EASE_SAMPLES + 1 }, (_, i) => curve(i / EASE_SAMPLES).toFixed(4))
    easing = `linear(${points.join(", ")})`
  }
  easeCache.set(spec, easing)
  return easing
}

const getEffect = (effect, em) => {
  switch (effect) {
    case "fade":
      return { from: { opacity: 0 }, to: { opacity: 1 }, ease: "power2.inOut" }
    case "blur":
      return {
        from: { opacity: 0, filter: `blur(${Math.round(em * 1.4) / 10}px)` },
        to: { opacity: 1, filter: "blur(0px)" },
        ease: "power2.out"
      }
    case "flip": {
      const setup = { transformPerspective: em * 6, transformOrigin: "50% 100%" }
      return {
        from: { ...setup, opacity: 0, rotationX: -90 },
        to: { ...setup, opacity: 1, rotationX: 0 },
        ease: "power3.out"
      }
    }
    case "pop":
      return { from: { opacity: 0, scale: 0 }, to: { opacity: 1, scale: 1 }, ease: "back.out(1.6)" }
    case "skew":
      return {
        from: { transformOrigin: "50% 100%", opacity: 0, x: -em * 0.4, skewX: -24 },
        to: { transformOrigin: "50% 100%", opacity: 1, x: 0, skewX: 0 },
        ease: "expo.out"
      }
    case "wave":
      return { from: { opacity: 0, y: em * 0.45 }, to: { opacity: 1, y: 0 }, ease: waveEase }
    default:
      return { from: { ...DEFAULT_FROM }, to: { ...DEFAULT_TO }, ease: "power3.out" }
  }
}

const unit = (value, suffix) => (typeof value === "number" ? `${value}${suffix}` : value)

const offsetOf = (vars, axis, used) => {
  if (!used.has(axis) && !used.has(`${axis}Percent`)) return null
  const px = unit(vars[axis] ?? 0, "px")
  return vars[`${axis}Percent`] === undefined ? px : `calc(${px} + ${vars[`${axis}Percent`]}%)`
}

const usedKeys = (list) => {
  const used = new Set()
  list.forEach((vars) =>
    Object.keys(vars).forEach((key) => {
      if (TRANSFORM_KEYS.has(key) && key !== "transformOrigin") used.add(key)
    })
  )
  return used
}

const transformOf = (vars, used, perspective) => {
  const parts = []
  if (used.has("transformPerspective")) parts.push(`perspective(${vars.transformPerspective ?? perspective}px)`)
  const x = offsetOf(vars, "x", used)
  const y = offsetOf(vars, "y", used)
  if (x !== null || y !== null) parts.push(`translate(${x ?? "0px"}, ${y ?? "0px"})`)
  if (used.has("rotation")) parts.push(`rotate(${vars.rotation ?? 0}deg)`)
  if (used.has("rotationX")) parts.push(`rotateX(${vars.rotationX ?? 0}deg)`)
  if (used.has("rotationY")) parts.push(`rotateY(${vars.rotationY ?? 0}deg)`)
  if (used.has("skewX")) parts.push(`skewX(${vars.skewX ?? 0}deg)`)
  if (used.has("skewY")) parts.push(`skewY(${vars.skewY ?? 0}deg)`)
  if (used.has("scale") || used.has("scaleX") || used.has("scaleY")) {
    parts.push(`scale(${vars.scaleX ?? vars.scale ?? 1}, ${vars.scaleY ?? vars.scale ?? 1})`)
  }
  return parts.join(" ")
}

const framesOf = (list, easing) => {
  const used = usedKeys(list)
  const perspective = list.map((vars) => vars.transformPerspective).find((value) => value !== undefined)
  return list.map((vars, index) => {
    const frame = {}
    if (used.size) frame.transform = transformOf(vars, used, perspective)
    Object.keys(vars).forEach((key) => {
      if (!NON_FRAME_KEYS.has(key)) frame[key] = vars[key]
    })
    if (index < list.length - 1) frame.easing = easing
    return frame
  })
}

const dashed = (key) => key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)

const applyInline = (piece, vars) => {
  const used = usedKeys([vars])
  piece.style.transform = used.size ? transformOf(vars, used, vars.transformPerspective) : ""
  Object.keys(vars).forEach((key) => {
    if (!NON_FRAME_KEYS.has(key)) piece.style[key] = String(vars[key])
  })
}

const clearInline = (piece, keys) => {
  piece.style.removeProperty("transform")
  piece.style.removeProperty("will-change")
  keys.forEach((key) => piece.style.removeProperty(dashed(key)))
}

const settled = (animations) => Promise.allSettled(animations.map((animation) => animation.finished))

const tidyStyle = (element) => {
  if (!element.getAttribute("style")) element.removeAttribute("style")
}

const fontsLoaded = () => !document.fonts || document.fonts.status === "loaded"

const span = (className, display) => {
  const node = document.createElement("span")
  node.className = className
  node.style.display = display
  node.setAttribute("aria-hidden", "true")
  return node
}

const shuffleRanks = (count, seedText) => {
  let seed = 2166136261
  for (let i = 0; i < seedText.length; i++) seed = Math.imul(seed ^ seedText.charCodeAt(i), 16777619) >>> 0
  const next = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const order = Array.from({ length: count }, (_, i) => i)
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1))
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  const ranks = []
  order.forEach((piece, rank) => {
    ranks[piece] = rank
  })
  return ranks
}

const buildRanks = (count, staggerFrom, seedText) => {
  const mid = (count - 1) / 2
  if (staggerFrom === "random") return shuffleRanks(count, seedText)
  return Array.from({ length: count }, (_, i) => {
    if (staggerFrom === "end") return count - 1 - i
    if (staggerFrom === "center") return Math.abs(i - mid)
    if (staggerFrom === "edges") return Math.min(i, count - 1 - i)
    if (typeof staggerFrom === "number") return Math.abs(i - staggerFrom)
    return i
  })
}

export default class SplitText {
  constructor(element, options = {}) {
    this.element = element
    this.options = { ...DEFAULTS, ...options }
    this.original = element.innerHTML
    this.sourceText = element.textContent
    this.label = element.getAttribute("aria-label")
    this.inline = { overflow: element.style.overflow, visibility: element.style.visibility }
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    this.completedText = null
    this.token = 0
    this.running = []
    this.alive = true
    this.built = false

    this.onEnter = this.onEnter.bind(this)
    this.onMove = this.onMove.bind(this)
    this.onLeave = this.onLeave.bind(this)
    this.onClick = this.onClick.bind(this)
    this.tick = this.tick.bind(this)

    this.begin()
  }

  update(options = {}) {
    if (!this.alive) return
    this.options = { ...this.options, ...options }
    this.teardown()
    this.begin()
  }

  destroy() {
    if (!this.alive) return
    this.alive = false
    this.teardown()
    this.element.style.visibility = this.inline.visibility
    tidyStyle(this.element)
  }

  begin() {
    if (fontsLoaded()) {
      this.start()
      return
    }
    const token = ++this.token
    this.element.style.visibility = "hidden"
    document.fonts.ready.then(() => {
      if (this.alive && token === this.token) this.start()
    })
  }

  start() {
    const element = this.element
    const options = this.options
    element.style.visibility = this.inline.visibility
    const text = options.text ?? this.sourceText
    if (!text || !text.trim()) return
    if (this.reduced) {
      this.finish(text)
      return
    }

    this.text = text
    this.revealed = this.completedText === text
    this.em = parseFloat(getComputedStyle(element).fontSize) || 16
    this.custom = options.from !== undefined || options.to !== undefined
    const look = getEffect(options.effect, this.em)
    this.from = this.custom ? { ...(options.from || DEFAULT_FROM) } : look.from
    this.to = this.custom ? { ...(options.to || DEFAULT_TO) } : look.to
    this.easing = cssEasing(options.ease || (this.custom ? "power3.out" : look.ease))
    this.exitDuration = Math.max(MIN_EXIT_DURATION, options.duration * EXIT_DURATION_SCALE)
    this.inlineKeys = [...new Set([...Object.keys(this.from), ...Object.keys(this.to)])].filter(
      (key) => !NON_FRAME_KEYS.has(key)
    )
    const clip =
      options.hoverEffect === "none" &&
      (options.from !== undefined || options.to !== undefined || options.effect === "rise" || options.effect === "fade")
    element.style.overflow = clip ? "hidden" : this.inline.overflow

    this.split()
    this.ranks = buildRanks(this.pieces.length, options.staggerFrom, text)
    this.springs = []
    this.kicks = []
    this.centers = null
    this.pointer = { x: 0, y: 0, inside: false }
    this.raf = 0
    this.last = 0
    this.phase = this.revealed ? "rest" : "from"
    this.busy = false
    this.queued = 0
    this.built = true

    element.addEventListener("pointerenter", this.onEnter)
    element.addEventListener("pointermove", this.onMove)
    element.addEventListener("pointerleave", this.onLeave)
    element.addEventListener("click", this.onClick)
    if (options.splitType.includes("lines")) this.observeWidth()

    if (this.revealed) {
      this.queue()
      return
    }
    this.hold()
    if (options.trigger === "load") {
      this.runIn()
      return
    }
    try {
      this.observer = new IntersectionObserver(this.onIntersect.bind(this), {
        threshold: options.threshold,
        rootMargin: options.rootMargin
      })
    } catch {
      this.observer = new IntersectionObserver(this.onIntersect.bind(this), { threshold: options.threshold })
    }
    this.observer.observe(element)
  }

  teardown() {
    this.token++
    clearTimeout(this.queued)
    this.queued = 0
    cancelAnimationFrame(this.raf)
    this.raf = 0
    clearTimeout(this.resplitTimer)
    this.observer?.disconnect()
    this.observer = null
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.running.forEach((animation) => animation.cancel())
    this.running = []
    if (this.built) {
      this.element.removeEventListener("pointerenter", this.onEnter)
      this.element.removeEventListener("pointermove", this.onMove)
      this.element.removeEventListener("pointerleave", this.onLeave)
      this.element.removeEventListener("click", this.onClick)
      this.element.innerHTML = this.original
      this.element.style.overflow = this.inline.overflow
      tidyStyle(this.element)
      if (this.label === null) this.element.removeAttribute("aria-label")
      else this.element.setAttribute("aria-label", this.label)
      this.built = false
    }
  }

  finish(text) {
    if (this.completedText === text) return
    this.completedText = text
    this.options.onLetterAnimationComplete?.()
  }

  observeWidth() {
    let width = this.element.getBoundingClientRect().width
    this.resizeObserver = new ResizeObserver(() => {
      const next = this.element.getBoundingClientRect().width
      if (Math.abs(next - width) < 1) return
      width = next
      clearTimeout(this.resplitTimer)
      this.resplitTimer = setTimeout(() => {
        this.teardown()
        this.begin()
      }, RESPLIT_DELAY)
    })
    this.resizeObserver.observe(this.element)
  }

  split() {
    const element = this.element
    const options = this.options
    const types = options.splitType
    this.wantChars = types.includes("chars")
    this.unit = this.wantChars ? "chars" : types.includes("words") ? "words" : "lines"
    this.wantLines = types.includes("lines")
    this.chars = []
    this.words = []
    this.lines = []
    this.masks = []
    this.wordNodes = []

    element.innerHTML = this.original
    if (options.text !== undefined || this.wantLines) element.textContent = this.text
    this.splitNode(element)
    if (this.wantLines) this.groupLines()

    const list = [this[this.unit], this.chars, this.words, this.lines].find((items) => items.length) || []
    this.pieces = list
    this.movers = options.mask && this.masks.length === list.length ? this.masks : list
    element.setAttribute("aria-label", this.text.replace(/\s+/g, " ").trim())
    this.pieces.forEach((piece) => {
      if (this.from.transformOrigin) piece.style.transformOrigin = this.from.transformOrigin
    })
  }

  splitNode(node) {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE) this.splitText(child)
      else if (child.nodeType === Node.ELEMENT_NODE && child.tagName !== "BR") this.splitNode(child)
    }
  }

  splitText(textNode) {
    const fragment = document.createDocumentFragment()
    textNode.nodeValue.split(/(\s+)/).forEach((token) => {
      if (!token) return
      if (/^\s+$/.test(token)) fragment.append(token)
      else fragment.append(this.makeWord(token))
    })
    textNode.replaceWith(fragment)
  }

  makeWord(token) {
    const word = span(WORD_CLASS, "inline-block")
    word.style.whiteSpace = "nowrap"
    if (this.wantChars) {
      Array.from(token).forEach((letter) => {
        const char = span(CHAR_CLASS, "inline-block")
        char.textContent = letter
        this.chars.push(char)
        word.append(this.options.mask && this.unit === "chars" ? this.maskOf(char, "inline-block") : char)
      })
    } else {
      word.textContent = token
    }
    this.words.push(word)
    const top = this.options.mask && this.unit === "words" ? this.maskOf(word, "inline-block") : word
    this.wordNodes.push(top)
    return top
  }

  maskOf(node, display) {
    const mask = span(MASK_CLASS, display)
    mask.style.overflow = "clip"
    node.before(mask)
    mask.append(node)
    this.masks.push(mask)
    return mask
  }

  groupLines() {
    const rows = []
    this.wordNodes.forEach((node) => {
      const rect = node.getBoundingClientRect()
      const middle = rect.top + rect.height / 2
      const row = rows[rows.length - 1]
      if (row && middle - row.middle <= rect.height * LINE_TOLERANCE) row.nodes.push(node)
      else rows.push({ middle, nodes: [node] })
    })
    rows.forEach((row) => {
      const line = span(LINE_CLASS, "block")
      const first = row.nodes[0]
      const last = row.nodes[row.nodes.length - 1]
      first.before(line)
      let node = first
      while (node) {
        const next = node.nextSibling
        line.append(node)
        if (node === last) break
        node = next
      }
      this.lines.push(line)
    })
    if (this.options.mask && this.unit === "lines") {
      this.lines.forEach((line) => this.maskOf(line, "block"))
    }
  }

  hold() {
    this.pieces.forEach((piece) => {
      applyInline(piece, this.from)
      piece.style.willChange = "transform, opacity"
    })
  }

  replace(animations) {
    const previous = this.running
    this.running = animations
    previous.forEach((animation) => animation.cancel())
  }

  playIn() {
    const options = this.options
    const accent = options.accentColor
    const duration = options.duration * MILLISECONDS
    const base = accent ? getComputedStyle(this.element).color : null
    const animations = []
    this.pieces.forEach((piece, index) => {
      const delay = this.ranks[index] * options.delay
      piece.style.willChange = "transform, opacity"
      animations.push(
        piece.animate(framesOf([this.from, this.to], this.easing), {
          duration,
          delay,
          fill: "both",
          easing: "linear"
        })
      )
      if (accent) {
        animations.push(
          piece.animate([{ color: accent }, { color: base }], {
            duration: duration * ACCENT_DURATION_SCALE,
            delay: delay + duration * ACCENT_DELAY_SCALE,
            fill: "both",
            easing: cssEasing("power1.inOut")
          })
        )
      }
    })
    this.replace(animations)
    return animations
  }

  playOut() {
    const options = this.options
    const accent = options.accentColor
    const duration = this.exitDuration * MILLISECONDS
    const animations = []
    this.pieces.forEach((piece, index) => {
      const delay = this.ranks[index] * options.delay
      piece.style.willChange = "transform, opacity"
      animations.push(
        piece.animate(framesOf([this.to, this.from], "linear"), {
          duration,
          delay,
          fill: "forwards",
          easing: cssEasing("power2.in")
        })
      )
      if (accent) {
        animations.push(
          piece.animate([{}, { color: accent }], {
            duration,
            delay,
            fill: "forwards",
            easing: cssEasing("power1.in")
          })
        )
      }
    })
    this.replace(animations)
    return animations
  }

  async runIn() {
    const token = this.token
    this.busy = true
    this.phase = "in"
    await settled(this.playIn())
    if (token !== this.token) return
    this.pieces.forEach((piece) => {
      clearInline(piece, [...this.inlineKeys, "color"])
      if (this.custom) applyInline(piece, this.to)
    })
    this.replace([])
    this.busy = false
    this.phase = "rest"
    this.revealed = true
    this.finish(this.text)
    this.queue()
  }

  async cycle() {
    if (this.busy || !this.revealed || !this.pieces.length) return
    const token = this.token
    clearTimeout(this.queued)
    this.queued = 0
    this.busy = true
    this.phase = "out"
    await settled(this.playOut())
    if (token !== this.token) return
    await this.runIn()
  }

  queue() {
    clearTimeout(this.queued)
    this.queued = 0
    if (!this.options.loop) return
    this.queued = setTimeout(() => this.cycle(), this.options.loopDelay * MILLISECONDS)
  }

  onIntersect(entries) {
    if (!entries.some((entry) => entry.isIntersecting)) return
    this.observer.disconnect()
    this.observer = null
    if (this.phase === "from") this.runIn()
  }

  measure() {
    const box = this.element.getBoundingClientRect()
    this.centers = this.movers.map((node, i) => {
      const rect = node.getBoundingClientRect()
      return {
        x: rect.left + rect.width / 2 - box.left,
        y: rect.top + rect.height / 2 - box.top - (this.springs[i]?.y || 0)
      }
    })
  }

  tick(now) {
    this.raf = 0
    const dt = Math.min(0.032, Math.max(0.001, (now - this.last) / 1000))
    this.last = now
    const spots = this.options.hoverEffect === "lift" && this.pointer.inside && this.revealed ? this.centers : null
    const radius = this.em * 1.15
    const lift = this.em * 0.2
    let moving = false
    for (let k = this.kicks.length - 1; k >= 0; k--) {
      if (now < this.kicks[k].at) continue
      const spring = this.springs[this.kicks[k].index]
      if (spring) spring.v -= this.kicks[k].velocity
      this.kicks.splice(k, 1)
    }
    this.movers.forEach((node, i) => {
      const spring = this.springs[i] || (this.springs[i] = { y: 0, v: 0 })
      const spot = spots?.[i]
      let target = 0
      if (spot) {
        const dx = (spot.x - this.pointer.x) / radius
        const dy = (spot.y - this.pointer.y) / (radius * 1.4)
        target = -lift * Math.exp(-(dx * dx + dy * dy) * 0.5)
      }
      spring.v += (STIFFNESS * (target - spring.y) - DAMPING * spring.v) * dt
      spring.y += spring.v * dt
      if (Math.abs(target - spring.y) < 0.02 && Math.abs(spring.v) < 0.05) {
        spring.y = target
        spring.v = 0
      } else {
        moving = true
      }
      node.style.translate = Math.abs(spring.y) > 0.01 ? `0 ${spring.y.toFixed(2)}px` : ""
    })
    if (moving || this.kicks.length) this.raf = requestAnimationFrame(this.tick)
  }

  wake() {
    if (this.raf) return
    this.last = performance.now()
    this.raf = requestAnimationFrame(this.tick)
  }

  locate(event) {
    const box = this.element.getBoundingClientRect()
    this.pointer.x = event.clientX - box.left
    this.pointer.y = event.clientY - box.top
  }

  onEnter(event) {
    const options = this.options
    this.locate(event)
    this.pointer.inside = true
    if (!this.revealed) return
    if (options.trigger === "hover") this.cycle()
    if (options.hoverEffect === "none") return
    this.measure()
    if (options.hoverEffect === "wave") {
      const now = performance.now()
      const speed = this.em * 9
      const velocity = (this.em * 0.16) / KICK
      this.centers.forEach((center, index) => {
        this.kicks.push({ index, velocity, at: now + (Math.abs(center.x - this.pointer.x) / speed) * MILLISECONDS })
      })
    }
    this.wake()
  }

  onMove(event) {
    this.locate(event)
    this.pointer.inside = true
    if (!this.revealed || this.options.hoverEffect !== "lift") return
    if (!this.centers) this.measure()
    this.wake()
  }

  onLeave() {
    this.pointer.inside = false
    this.wake()
  }

  onClick() {
    if (this.options.trigger === "click") this.cycle()
  }
}
