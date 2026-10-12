import { Controller } from "@hotwired/stimulus"

const GAP = 4
const LAYERS = 3
const TOP = 30
const FOOT = 30
const PILL_H = 22
const PIN_INSET = 3

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

const F = (n) => Number(n || 0).toLocaleString("en-US")

const compact = (n) => {
  const v = Number(n || 0)
  if (Math.abs(v) >= 1e6) return `${+(v / 1e6).toFixed(1)}m`
  if (Math.abs(v) >= 1e4) return `${Math.round(v / 1e3)}k`
  if (Math.abs(v) >= 1e3) return `${+(v / 1e3).toFixed(1)}k`
  return F(v)
}

const share = (part, total) => {
  if (!(total > 0)) return null
  const pct = (part / total) * 100
  return pct >= 10 || pct === 0 ? `${Math.round(pct)}%` : `${pct.toFixed(1)}%`
}

const MEASURE_CTX = typeof document === "undefined"
  ? null
  : document.createElement("canvas").getContext("2d")

function textWidth(text) {
  if (!MEASURE_CTX) return String(text).length * 7
  MEASURE_CTX.font = '700 12px Geist, ui-sans-serif, system-ui, sans-serif'
  return MEASURE_CTX.measureText(String(text)).width
}

function band(norm0, norm1, x, w, my, h, scale) {
  const h0 = norm0 * h * 0.44 * scale
  const h1 = norm1 * h * 0.44 * scale
  const cx = w * 0.55
  return `M ${x} ${my - h0} C ${x + cx} ${my - h0}, ${x + w - cx} ${my - h1}, ${x + w} ${my - h1}` +
    ` L ${x + w} ${my + h1} C ${x + w - cx} ${my + h1}, ${x + cx} ${my + h0}, ${x} ${my + h0} Z`
}

const withoutPin = ({ pin: _pin, ...view }) => JSON.stringify(view)

export default class extends Controller {
  static values = { stages: Array, height: Number, seriesColor: Number, label: String, view: Object }

  connect() {
    this.at = null
    this.firstDraw = true
    this.wide = 0
    this.fillHeight = 0
    const hover = this.externalPointer ? "" : "mousemove->funnel#track mouseleave->funnel#clear "
    this.element.innerHTML = `<div class="chart funnel tipped" tabindex="0"
      data-action="${hover}keydown->funnel#key"
      ><div class="tip"></div><span class="chart-caption" aria-live="polite"></span></div>`
    const box = this.element.querySelector(".chart")
    this.observer = new ResizeObserver(() => this.measure())
    this.observer.observe(box)
    this.measure()
    this.ready = true
    if (this.hasViewValue) this.dispatch("ready", { prefix: "chart" })
  }

  disconnect() {
    this.ready = false
    this.observer?.disconnect()
    clearTimeout(this.enterTimer)
  }

  viewValueChanged(value, previous) {
    if (!this.ready) return

    this.redraw()
    if (!previous || withoutPin(value) !== withoutPin(previous)) this.dispatch("update", { prefix: "chart" })
  }

  get stages() {
    return (this.stagesValue || []).filter((s) => s && s.value != null)
  }

  get fill() {
    return !!this.viewValue.fill
  }

  get externalPointer() {
    return this.viewValue.pointer === "external"
  }

  get showLabels() {
    return this.viewValue.labels !== false
  }

  get pinned() {
    return Number.isInteger(this.viewValue.pin) ? this.viewValue.pin : null
  }

  get seriesColor() {
    return this.hasSeriesColorValue ? this.seriesColorValue : 1
  }

  get unit() {
    return this.hasLabelValue && this.labelValue ? this.labelValue : "count"
  }

  get high() {
    if (this.fill && this.fillHeight > 0) return this.fillHeight
    return this.hasHeightValue && this.heightValue > 0 ? this.heightValue : 260
  }

  measure() {
    const box = this.element.querySelector(".chart")
    const wide = box ? box.clientWidth : 0
    const height = this.fill && box ? box.clientHeight : 0
    if (!wide || (wide === this.wide && height === this.fillHeight)) return

    this.wide = wide
    this.fillHeight = height
    this.draw(box, wide)
  }

  redraw() {
    const box = this.element.querySelector(".chart")
    if (box && this.wide) this.draw(box, this.wide)
  }

  draw(box, wide) {
    const stages = this.stages
    if (!stages.length) return

    const n = stages.length
    const high = this.high
    const h = high - TOP - FOOT
    const my = TOP + h / 2
    const segW = (wide - GAP * (n - 1)) / n
    const first = Number(stages[0].value) || 0
    const norms = stages.map((s) => (first > 0 ? Math.max(Number(s.value) || 0, 0) / first : 0))
    const seriesColor = this.seriesColor
    const labels = this.showLabels

    const segs = stages.map((stage, i) => {
      const x = i * (segW + GAP)
      const n0 = Math.max(norms[i], 0.012)
      const n1 = Math.max(i < n - 1 ? norms[i + 1] : norms[i], 0.012)
      const layerPaths = Array.from({ length: LAYERS }, (_, l) => {
        const scale = 1 - (l / LAYERS) * 0.35
        const opacity = 0.18 + (l / (LAYERS - 1)) * 0.65
        return `<path d="${band(n0, n1, x, segW, my, h, scale)}" fill="currentColor"
          fill-opacity="${opacity.toFixed(2)}"/>`
      }).join("")

      const pct = share(Number(stage.value) || 0, first) || "n/a"
      const pillW = textWidth(pct) + 24
      const cx = x + segW / 2
      const labelMarkup = labels
        ? `<text class="funnel-value" x="${cx.toFixed(1)}" y="${TOP - 10}" text-anchor="middle">${
          esc(compact(stage.value))}</text>` +
          `<g class="funnel-pill"><rect x="${(cx - pillW / 2).toFixed(1)}" y="${(my - PILL_H / 2).toFixed(1)}"
          width="${pillW.toFixed(1)}" height="${PILL_H}" rx="6"/><text x="${cx.toFixed(1)}"
          y="${(my + 4).toFixed(1)}" text-anchor="middle">${esc(pct)}</text></g>`
        : ""
      return `<g class="funnel-seg ser-${seriesColor}" data-i="${i}" style="--i:${i}">${layerPaths}</g>` +
        `<g class="funnel-says" data-i="${i}" style="--i:${i}">${labelMarkup}` +
        `<text class="ax funnel-stage" x="${cx.toFixed(1)}" y="${high - 10}" text-anchor="middle">${
          esc(stage.label)}</text></g>`
    }).join("")

    const pin = this.pinned
    const pinOutline = pin != null && pin < n
      ? `<rect class="pin-ring" x="${(pin * (segW + GAP) - PIN_INSET).toFixed(1)}" y="${TOP - PIN_INSET}"
          width="${(segW + PIN_INSET * 2).toFixed(1)}" height="${(h + PIN_INSET * 2).toFixed(1)}" rx="8"/>`
      : ""

    const separators = stages.slice(1).map((_, i) => {
      const at = (i + 1) * (segW + GAP) - GAP / 2
      return `<line class="funnel-seam" x1="${at.toFixed(1)}" y1="${TOP}" x2="${at.toFixed(1)}"
        y2="${(TOP + h).toFixed(1)}"/>`
    }).join("")

    box.querySelector("svg")?.remove()
    box.insertAdjacentHTML("afterbegin",
      `<svg width="${wide}" height="${high}" viewBox="0 0 ${wide} ${high}" role="img"
        aria-label="${esc(this.summary(stages))}">${separators}${segs}${pinOutline}</svg>`)

    this.geom = { wide, high, segW, n, first, my }
    if (this.firstDraw) {
      this.firstDraw = false
      box.classList.add("is-entering")
      clearTimeout(this.enterTimer)
      this.enterTimer = setTimeout(() => box.classList.remove("is-entering"), 1600)
    }
    if (this.at != null) this.show(Math.min(this.at, n - 1), { silent: true })
  }

  summary(stages) {
    const first = Number(stages[0].value) || 0
    const label = this.hasLabelValue && this.labelValue ? this.labelValue : "funnel"
    return `${label}: ${stages.map((s) =>
      `${s.label} ${F(s.value)} (${share(Number(s.value) || 0, first) || "n/a"})`).join(", ")}`
  }

  indexAtPointer(event) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    const mx = event.clientX - box.left
    if (mx < 0 || mx > g.wide) return null
    return Math.min(g.n - 1, Math.max(0, Math.floor(mx / (g.segW + GAP))))
  }

  track(event) {
    const i = this.indexAtPointer(event)
    if (i == null) return this.clear()
    if (i !== this.at) this.show(i)
  }

  key(event) {
    const g = this.geom
    if (!g) return

    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    let next = this.at
    if (step) next = this.at == null ? (step > 0 ? 0 : g.n - 1) : Math.min(g.n - 1, Math.max(0, this.at + step))
    else if (event.key === "Home") next = 0
    else if (event.key === "End") next = g.n - 1
    else if (event.key === "Escape") return this.clear()
    else return

    event.preventDefault()
    this.show(next, { source: "keyboard" })
  }

  showIndex(index) {
    if (!this.geom) {
      this.announcePoint(index, "table")
      return
    }
    this.show(index, { source: "table" })
  }

  announcePoint(index, source) {
    if (!this.hasViewValue || index === this.announcedIndex) return

    this.announcedIndex = index
    this.dispatch("point", { prefix: "chart", detail: { index, source } })
  }

  show(i, { source = "pointer", silent = false } = {}) {
    const g = this.geom
    const stages = this.stages
    const stage = stages[i]
    if (!g || !stage) return

    this.at = i
    if (!silent) this.announcePoint(i, source)
    const box = this.element.querySelector(".chart")
    const value = Number(stage.value) || 0
    const prev = i > 0 ? Number(stages[i - 1].value) || 0 : null
    const seriesColor = this.seriesColor

    const tip = box.querySelector(".tip")
    tip.innerHTML = `<div class="t">${esc(stage.label)}</div>` +
      `<div class="row"><i class="ser-${seriesColor}"></i>${esc(this.labelValue || "count")}<b>${F(value)}</b></div>` +
      (i > 0 ? `<div class="row"><i class="ser-none"></i>of ${esc(stages[0].label)}<b>${
        share(value, g.first) || "n/a"}</b></div>` : "") +
      (prev != null ? `<div class="row"><i class="ser-none"></i>of the step before<b>${
        share(value, prev) || "n/a"}</b></div>` : "") +
      (stage.note ? `<div class="row row-note"><i></i>${esc(stage.note)}</div>` : "")
    tip.classList.add("on")

    const tipWide = tip.offsetWidth || 180
    const left = i * (g.segW + GAP) + g.segW + 8
    tip.style.left = `${left + tipWide > g.wide ? Math.max(0, i * (g.segW + GAP) - tipWide - 8) : left}px`
    tip.style.top = `${TOP}px`

    box.classList.add("lit")
    box.querySelectorAll(".funnel-seg, .funnel-says").forEach((seg) =>
      seg.classList.toggle("on", +seg.dataset.i === i))
    box.querySelector(".chart-caption").textContent =
      `${stage.label}, ${F(value)}, ${share(value, g.first) || "n/a"} of ${stages[0].label}`
  }

  clear() {
    const box = this.element.querySelector(".chart")
    if (!box) return

    this.at = null
    this.announcePoint(null, "pointer")
    box.querySelector(".tip")?.classList.remove("on")
    box.classList.remove("lit")
    box.querySelectorAll(".funnel-seg.on, .funnel-says.on").forEach((seg) => seg.classList.remove("on"))
    const caption = box.querySelector(".chart-caption")
    if (caption) caption.textContent = ""
  }

  pointKey(index) {
    const stage = this.stages[index]
    return stage ? String(stage.label) : null
  }

  indexOfKey(key) {
    return this.stages.findIndex((stage) => String(stage.label) === key)
  }

  displayDefaults() {
    return { labels: true }
  }

  displayOptions() {
    return { labels: true }
  }

  inspectorLabels() {
    return { point: "Step", stats: "All steps" }
  }

  pointDetails(i) {
    const stages = this.stages
    const stage = stages[i]
    if (!stage) return null

    const value = Number(stage.value) || 0
    const first = Number(stages[0].value) || 0
    const prev = i > 0 ? Number(stages[i - 1].value) || 0 : null
    const row = (label, text, extra = {}) => ({
      label, colorClass: "", color: null, shape: "none", value: text, change: null, share: null, ...extra
    })
    return {
      title: stage.label,
      qualifier: `step ${i + 1} of ${stages.length}`,
      tags: [],
      note: stage.note || null,
      total: null,
      values: [
        row(this.unit, F(value), { colorClass: `ser-${this.seriesColor}`, shape: "box" }),
        i > 0 && row(`of ${stages[0].label}`, share(value, first) || "n/a"),
        prev != null && row("of the step before", share(value, prev) || "n/a"),
        prev != null && row("lost from the step before", F(Math.max(prev - value, 0)))
      ].filter(Boolean)
    }
  }

  rangeStats() {
    const stages = this.stages
    if (!stages.length) return null

    const values = stages.map((stage) => Number(stage.value) || 0)
    const first = values[0]
    const last = values[values.length - 1]
    const drops = values.slice(1).map((value, k) => ({
      label: stages[k + 1].label, retention: values[k] > 0 ? value / values[k] : null
    })).filter((drop) => drop.retention != null)
    const largestDrop = drops.reduce((low, drop) => (low && low.retention <= drop.retention ? low : drop), null)
    return {
      summary: [
        { label: stages[0].label, value: F(first) },
        stages.length > 1 && { label: stages[stages.length - 1].label, value: F(last) },
        stages.length > 1 && { label: "conversion", value: share(last, first) || "n/a" },
        largestDrop && { label: `largest drop, to ${largestDrop.label}`, value: share(1 - largestDrop.retention, 1) || "n/a" }
      ].filter(Boolean)
    }
  }

  tableData() {
    const stages = this.stages
    const values = stages.map((stage) => Number(stage.value) || 0)
    const first = values[0]
    const ratio = (part, total) => (total > 0 ? Number(((part / total) * 100).toFixed(3)) : null)
    return {
      columns: [
        { key: "label", label: "Step", numeric: false },
        { key: "value", label: this.unit, numeric: true },
        { key: "first", label: stages.length ? `of ${stages[0].label}` : "of first", numeric: true },
        { key: "before", label: "of the step before", numeric: true },
        { key: "lost", label: "lost", numeric: true }
      ],
      rows: stages.map((stage, index) => {
        const value = values[index]
        const prev = index > 0 ? values[index - 1] : null
        const lost = prev == null ? null : Math.max(prev - value, 0)
        return {
          index,
          values: {
            label: stage.label, value, first: ratio(value, first),
            before: prev == null ? null : ratio(value, prev), lost
          },
          display: {
            label: stage.label, value: F(value), first: share(value, first) || "n/a",
            before: prev == null ? "" : share(value, prev) || "n/a", lost: lost == null ? "" : F(lost)
          },
          note: null
        }
      }),
      footer: null
    }
  }
}
