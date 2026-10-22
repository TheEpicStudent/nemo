const ROOT_CLASS = "text-type"
const SINE_IN_OUT = "cubic-bezier(0.37, 0, 0.63, 1)"
const GLIDE_EASE = "cubic-bezier(0.215, 0.61, 0.355, 1)"
const ZERO_WIDTH_SPACE = "​"
const BLINK_RESUME_MS = 120
const MIN_GLIDE_SECONDS = 0.06
const MAX_GLIDE_SECONDS = 0.18
const GLIDE_PER_MS = 0.0016
const TYPO_RATE = 0.16
const TYPO_FOLLOW_RATE = 0.4
const MIN_TYPO_DELETE_MS = 45
const MILLISECONDS = 1000

const DEFAULTS = {
  text: undefined,
  typingSpeed: 50,
  initialDelay: 0,
  pauseDuration: 2000,
  deletingSpeed: 30,
  deleteMode: "backspace",
  loop: true,
  showCursor: true,
  hideCursorWhileTyping: false,
  cursorStyle: "character",
  cursorCharacter: "|",
  cursorColor: "currentColor",
  cursorClassName: "",
  cursorBlinkDuration: 0.5,
  cursorGlide: true,
  typeEffect: "none",
  mistakes: 0,
  prefix: "",
  prefixColor: "currentColor",
  textColors: [],
  variableSpeed: undefined,
  onSentenceComplete: undefined,
  startOnVisible: false,
  reverseMode: false
}

const NEIGHBORS = {
  a: "qwsz",
  b: "vghn",
  c: "xdfv",
  d: "serfcx",
  e: "wsdr",
  f: "drtgvc",
  g: "ftyhbv",
  h: "gyujnb",
  i: "ujko",
  j: "huikmn",
  k: "jiolm",
  l: "kop",
  m: "njk",
  n: "bhjm",
  o: "iklp",
  p: "ol",
  q: "wa",
  r: "edft",
  s: "awedxz",
  t: "rfgy",
  u: "yhji",
  v: "cfgb",
  w: "qase",
  x: "zsdc",
  y: "tghu",
  z: "asx",
  0: "9p",
  1: "2q",
  2: "13w",
  3: "24e",
  4: "35r",
  5: "46t",
  6: "57y",
  7: "68u",
  8: "79i",
  9: "80o"
}

const EFFECTS = {
  fade: {
    keyframes: [{ opacity: 0 }, { opacity: 1 }],
    options: { duration: 360, easing: "cubic-bezier(0.25, 1, 0.5, 1)" }
  },
  blur: {
    keyframes: [
      { opacity: 0, filter: "blur(0.3em)" },
      { opacity: 1, filter: "blur(0em)" }
    ],
    options: { duration: 520, easing: "cubic-bezier(0.22, 1, 0.36, 1)" }
  },
  rise: {
    keyframes: [
      { opacity: 0, top: "0.6em" },
      { opacity: 1, top: "0em" }
    ],
    options: { duration: 480, easing: "cubic-bezier(0.34, 1.4, 0.64, 1)" }
  }
}

const graphemes = (value) => {
  if (typeof Intl !== "undefined" && Intl.Segmenter) {
    return Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(value), (part) => part.segment)
  }
  return Array.from(value)
}

const typoFor = (char) => {
  const keys = NEIGHBORS[char.toLowerCase()]
  if (!keys) return null
  const pick = keys[Math.floor(Math.random() * keys.length)]
  return char === char.toLowerCase() ? pick : pick.toUpperCase()
}

const span = (className, text) => {
  const node = document.createElement("span")
  node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

export default class TextType {
  constructor(element, options = {}) {
    this.element = element
    this.options = { ...DEFAULTS, ...options }
    this.original = element.innerHTML
    this.label = element.getAttribute("aria-label")
    this.sourceText = element.textContent.trim()
    this.query = window.matchMedia("(prefers-reduced-motion: reduce)")
    this.reduced = this.query.matches
    this.alive = true
    this.built = false

    this.onMotion = this.onMotion.bind(this)
    this.onVisibility = this.onVisibility.bind(this)

    this.query.addEventListener("change", this.onMotion)
    document.addEventListener("visibilitychange", this.onVisibility)
    this.start()
  }

  update(options = {}) {
    if (!this.alive) return
    this.options = { ...this.options, ...options }
    this.teardown()
    this.start()
  }

  destroy() {
    if (!this.alive) return
    this.alive = false
    this.query.removeEventListener("change", this.onMotion)
    document.removeEventListener("visibilitychange", this.onVisibility)
    this.teardown()
  }

  start() {
    const options = this.options
    const text = options.text ?? this.sourceText
    this.texts = (Array.isArray(text) ? text : [text ?? ""]).map(String)
    if (!this.texts.length) this.texts = [""]
    this.state = { textIndex: 0, count: 0, selected: 0, typo: null, deleting: false, lastTypo: -1 }
    this.nodes = new Map()
    this.charsCache = null
    this.caretPosition = null
    this.timer = 0
    this.blinkTimer = 0
    this.blinkAnimation = null
    this.glide = null
    this.started = !options.startOnVisible
    this.visible = true

    const element = this.element
    element.textContent = ""
    element.setAttribute("aria-label", options.prefix + this.texts.join(" "))
    this.addedClass = !element.classList.contains(ROOT_CLASS)
    element.classList.add(ROOT_CLASS)

    this.content = span("text-type__content")
    this.content.setAttribute("aria-hidden", "true")
    this.body = document.createElement("span")
    this.caret = span("text-type__caret", ZERO_WIDTH_SPACE)
    if (options.prefix) {
      const prefix = span("text-type__prefix", options.prefix)
      prefix.style.color = options.prefixColor
      this.content.append(prefix)
    }
    if (options.reverseMode) this.content.append(this.caret)
    this.content.append(this.body)
    if (!options.reverseMode) this.content.append(this.caret)
    element.append(this.content)

    this.cursor = null
    this.blink = null
    if (options.showCursor) {
      this.cursor = span(
        `text-type__cursor text-type__cursor--${options.cursorStyle} ${options.cursorClassName}`.trim()
      )
      this.cursor.setAttribute("aria-hidden", "true")
      if (options.cursorColor && options.cursorColor !== "currentColor") this.cursor.style.color = options.cursorColor
      this.blink = span("text-type__blink")
      if (options.cursorStyle === "character") this.blink.textContent = options.cursorCharacter
      else this.blink.append(span("text-type__shape"))
      this.cursor.append(this.blink)
      element.append(this.cursor)
    }
    this.built = true

    this.resizeObserver = new ResizeObserver(() => this.placeCursor(true))
    this.resizeObserver.observe(element)
    this.intersection = new IntersectionObserver(
      (entries) => {
        this.visible = entries.some((entry) => entry.isIntersecting)
        if (this.visible) {
          this.started = true
          this.step()
        } else {
          this.stop()
        }
      },
      { threshold: 0.1 }
    )
    this.intersection.observe(element)

    this.startBlink()
    if (this.reduced) this.settle()
    else {
      this.render()
      this.step()
    }
  }

  teardown() {
    this.stop()
    clearTimeout(this.blinkTimer)
    this.blinkTimer = 0
    this.blinkAnimation?.cancel()
    this.glide?.cancel()
    this.resizeObserver?.disconnect()
    this.intersection?.disconnect()
    if (!this.built) return
    this.element.innerHTML = this.original
    if (this.label === null) this.element.removeAttribute("aria-label")
    else this.element.setAttribute("aria-label", this.label)
    if (this.addedClass) this.element.classList.remove(ROOT_CLASS)
    if (!this.element.classList.length) this.element.removeAttribute("class")
    this.built = false
  }

  stop() {
    clearTimeout(this.timer)
    this.timer = 0
  }

  chars() {
    const index = this.state.textIndex % this.texts.length
    if (!this.charsCache || this.charsCache.index !== index) {
      this.charsCache = { index, list: graphemes(this.texts[index]) }
    }
    return this.charsCache.list
  }

  settle() {
    this.stop()
    this.state = { textIndex: 0, count: this.chars().length, selected: 0, typo: null, deleting: false, lastTypo: -1 }
    this.charsCache = null
    this.state.count = this.chars().length
    this.render()
  }

  startBlink() {
    const blink = this.blink
    if (!blink) return
    blink.style.opacity = "1"
    const duration = this.options.cursorBlinkDuration
    if (this.reduced || duration <= 0) return
    const hold = duration * 0.7
    const fade = duration * 0.45
    const gap = duration * 0.4
    const total = hold + fade + gap + fade
    this.blinkAnimation = blink.animate(
      [
        { opacity: 1, offset: 0 },
        { opacity: 1, offset: hold / total, easing: SINE_IN_OUT },
        { opacity: 0, offset: (hold + fade) / total },
        { opacity: 0, offset: (hold + fade + gap) / total, easing: SINE_IN_OUT },
        { opacity: 1, offset: 1 }
      ],
      { duration: total * MILLISECONDS, iterations: Infinity }
    )
  }

  holdBlink() {
    const animation = this.blinkAnimation
    if (!animation) return
    animation.pause()
    animation.currentTime = 0
    clearTimeout(this.blinkTimer)
    this.blinkTimer = setTimeout(() => {
      animation.currentTime = 0
      animation.play()
    }, BLINK_RESUME_MS)
  }

  placeCursor(instant) {
    const cursor = this.cursor
    if (!cursor) return
    const options = this.options
    const x = this.caret.offsetLeft
    const y = this.caret.offsetTop
    const last = this.caretPosition
    if (last && Math.abs(last.x - x) < 0.5 && Math.abs(last.y - y) < 0.5) return
    this.caretPosition = { x, y }
    cursor.style.transform = `translate(${x}px, ${y}px)`
    this.glide?.cancel()
    this.glide = null
    if (!(instant || !last || !options.cursorGlide || this.reduced || Math.abs(last.y - y) > 1)) {
      const minSpeed = options.variableSpeed?.min ?? options.typingSpeed
      const maxSpeed = options.variableSpeed?.max ?? options.typingSpeed
      const seconds = Math.min(MAX_GLIDE_SECONDS, Math.max(MIN_GLIDE_SECONDS, ((minSpeed + maxSpeed) / 2) * GLIDE_PER_MS))
      this.glide = cursor.animate(
        [{ transform: `translate(${last.x}px, ${last.y}px)` }, { transform: `translate(${x}px, ${y}px)` }],
        { duration: seconds * MILLISECONDS, easing: GLIDE_EASE }
      )
    }
    if (!instant) this.holdBlink()
  }

  charNode(key, char) {
    let node = this.nodes.get(key)
    if (node) return node
    node = span("text-type__char", char)
    this.nodes.set(key, node)
    const effect = EFFECTS[this.options.typeEffect]
    if (effect && !this.reduced) node.animate(effect.keyframes, effect.options)
    return node
  }

  render() {
    const options = this.options
    const state = this.state
    const chars = this.chars()
    const total = chars.length
    const shown = Math.min(state.count, total)
    const start = options.reverseMode ? total - shown : 0
    const marked = Math.min(state.selected, shown)
    const correct = chars.slice(start, start + shown).map((char, i) => ({
      key: start + i,
      char,
      marked: options.reverseMode ? i < marked : i >= shown - marked
    }))
    const mistyped = (state.typo?.tail ?? []).map((char, i) => ({ key: `typo-${i}`, char, marked: false }))
    if (options.reverseMode) mistyped.reverse()
    const ordered = options.reverseMode ? [...mistyped, ...correct] : [...correct, ...mistyped]

    const keys = new Set(ordered.map((item) => item.key))
    this.nodes.forEach((node, key) => {
      if (keys.has(key)) return
      node.remove()
      this.nodes.delete(key)
    })
    ordered.forEach((item, i) => {
      const node = this.charNode(item.key, item.char)
      node.classList.toggle("text-type__char--selected", item.marked)
      if (this.body.children[i] !== node) this.body.insertBefore(node, this.body.children[i] ?? null)
    })

    const index = state.textIndex % this.texts.length
    this.body.style.color = options.textColors.length ? options.textColors[index % options.textColors.length] : "inherit"
    const typing = shown < total || state.deleting || state.typo !== null
    this.cursor?.classList.toggle("text-type__cursor--hidden", options.hideCursorWhileTyping && typing)
    this.placeCursor(false)
  }

  step() {
    this.stop()
    if (!this.alive || !this.built || this.reduced || !this.started || !this.visible || document.hidden) return
    const options = this.options
    const state = this.state
    const chars = this.chars()
    const total = chars.length
    const shown = Math.min(state.count, total)
    const index = state.textIndex % this.texts.length
    const minSpeed = options.variableSpeed?.min ?? options.typingSpeed
    const maxSpeed = options.variableSpeed?.max ?? options.typingSpeed
    const speed = () => minSpeed + Math.random() * (maxSpeed - minSpeed)
    const wait = (ms, next) => {
      this.timer = setTimeout(() => {
        this.timer = 0
        next()
        this.render()
        this.step()
      }, ms)
    }

    if (!state.deleting) {
      const typo = state.typo
      if (typo) {
        if (!typo.fixing) {
          if (typo.tail.length < typo.plan.length) {
            wait(speed(), () => {
              state.typo = { ...typo, tail: typo.plan.slice(0, typo.tail.length + 1) }
            })
          } else {
            wait(260 + Math.random() * 320, () => {
              state.typo = { ...typo, fixing: true }
            })
          }
        } else if (typo.tail.length) {
          wait(Math.max(MIN_TYPO_DELETE_MS, options.deletingSpeed), () => {
            state.typo = { ...typo, tail: typo.tail.slice(0, -1) }
          })
        } else {
          wait(90 + Math.random() * 140, () => {
            state.typo = null
          })
        }
      } else if (shown < total) {
        const lead = shown === 0 ? options.initialDelay : 0
        const next = options.reverseMode ? total - shown - 1 : shown
        const wrong =
          options.mistakes > 0 && shown > 0 && state.lastTypo !== next ? typoFor(chars[next]) : null
        if (wrong && Math.random() < Math.min(1, options.mistakes) * TYPO_RATE) {
          state.lastTypo = next
          const plan = [wrong]
          const follow = chars[options.reverseMode ? next - 1 : next + 1]
          if (follow && follow.trim() && Math.random() < TYPO_FOLLOW_RATE) plan.push(follow)
          wait(lead + speed(), () => {
            state.typo = { plan, tail: [wrong], fixing: false }
          })
        } else {
          wait(lead + speed(), () => {
            state.count = shown + 1
          })
        }
      } else if (options.loop || index < this.texts.length - 1) {
        wait(options.pauseDuration, () => {
          state.deleting = true
        })
      }
    } else if (shown > 0) {
      if (options.deleteMode === "select") {
        if (state.selected < shown) {
          wait(options.deletingSpeed, () => {
            state.selected += 1
          })
        } else {
          wait(Math.max(160, options.deletingSpeed * 8), () => {
            state.selected = 0
            state.count = 0
          })
        }
      } else {
        wait(options.deletingSpeed, () => {
          state.count = shown - 1
        })
      }
    } else {
      wait(0, () => {
        options.onSentenceComplete?.(this.texts[index], index)
        state.lastTypo = -1
        state.selected = 0
        state.deleting = false
        state.textIndex = (index + 1) % this.texts.length
      })
    }
  }

  onMotion() {
    this.reduced = this.query.matches
    this.blinkAnimation?.cancel()
    this.blinkAnimation = null
    this.startBlink()
    if (this.reduced) this.settle()
    else this.step()
  }

  onVisibility() {
    if (document.hidden) this.stop()
    else this.step()
  }
}
