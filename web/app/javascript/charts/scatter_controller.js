import { Controller } from "@hotwired/stimulus"
import { scaleLinear, scaleSqrt } from "d3-scale"

const PAD = { left: 66, right: 16, top: 22, bottom: 60 }
const X_TITLE_INSET = 12
const Y_TITLE_INSET = 17
const CARD_RADIUS = [4, 15]
const EXPLORER_RADIUS = [5, 20]
const CORNERS = ["tl", "tr", "bl", "br"]
const HIT_DISTANCE = 26
const MIN_ZOOM_FRACTION = 1 / 50
const MIN_SELECTION_PIXELS = 8
const LABEL_LIMIT = 15
const LABEL_TOP = 6
const LOG_MANTISSAS = [1, 2, 5]
const DEFAULT_HEIGHT = 268

let sequence = 0

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

const F = (n) => (n == null ? "n/a" : Number(n).toLocaleString("en-US"))

const axisLabel = (v) =>
  Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `${Math.round(v)}`

const clamp = (value, low, high) => Math.min(Math.max(value, low), high)

const groupKey = (point) => `g${point.seriesColor == null ? 1 : point.seriesColor}`

const withoutViewport = ({ window: _window, pin: _pin, ...view }) => JSON.stringify(view)

function median(values) {
  const sorted = values.filter((value) => value != null).map(Number).sort((a, b) => a - b)
  if (!sorted.length) return null

  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function logTicks(low, high) {
  const decades = []
  const steps = []
  for (let exponent = Math.floor(Math.log10(low)); exponent <= Math.ceil(Math.log10(high)); exponent++) {
    LOG_MANTISSAS.forEach((mantissa) => {
      const value = mantissa * 10 ** exponent
      if (value >= low * 0.999 && value <= high * 1.001) (mantissa === 1 ? decades : steps).push(value)
    })
  }
  return decades.length >= 3 ? decades : [...decades, ...steps].sort((a, b) => a - b)
}

export default class extends Controller {
  static values = {
    points: Array, height: Number,
    xLabel: String, yLabel: String, nLabel: String,
    yPct: Boolean,
    xMid: Number, yMid: Number, xMidLabel: String, yMidLabel: String,
    corners: Object,
    view: Object
  }

  connect() {
    this.gid = `sc${++sequence}`
    this.at = null
    this.wide = 0
    this.fillHeight = 0
    const hover = this.externalPointer ? "" : "mousemove->scatter#track mouseleave->scatter#clear "
    this.element.innerHTML = `<div class="chart tipped" tabindex="0"
      data-action="${hover}keydown->scatter#key"
      ><div class="tip"></div><span class="chart-caption" aria-live="polite"></span></div>`
    const chart = this.element.querySelector(".chart")
    this.observer = new ResizeObserver(() => this.measure())
    this.observer.observe(chart)
    this.measure()
    this.ready = true
    if (this.hasViewValue) this.dispatch("ready", { prefix: "chart" })
  }

  disconnect() {
    this.ready = false
    this.observer?.disconnect()
  }

  viewValueChanged(value, previous) {
    if (!this.ready) return

    this.redraw()
    if (!previous || withoutViewport(value) !== withoutViewport(previous)) this.dispatch("update", { prefix: "chart" })
  }

  get fill() {
    return !!this.viewValue.fill
  }

  get externalPointer() {
    return this.viewValue.pointer === "external"
  }

  get hiddenGroups() {
    return new Set(this.viewValue.hidden || [])
  }

  get showGrid() {
    return this.viewValue.grid !== false
  }

  get showNotes() {
    return this.viewValue.notes !== false
  }

  get showLabels() {
    return this.hasViewValue && this.viewValue.labels !== false
  }

  get logX() {
    return this.viewValue.xScale === "log"
  }

  get high() {
    if (this.fill && this.fillHeight > 0) return this.fillHeight
    return this.hasHeightValue && this.heightValue > 0 ? this.heightValue : DEFAULT_HEIGHT
  }

  get hasNotes() {
    return this.hasXMidValue || this.hasYMidValue || (this.hasCornersValue && Object.keys(this.cornersValue).length > 0)
  }

  scaleX(value) {
    return this.logX ? Math.log10(Math.max(1, Number(value))) : Number(value)
  }

  measure() {
    const chart = this.element.querySelector(".chart")
    const wide = chart ? chart.clientWidth : 0
    const height = this.fill && chart ? chart.clientHeight : 0
    if (!wide || (wide === this.wide && height === this.fillHeight)) return

    this.wide = wide
    this.fillHeight = height
    this.draw(chart, wide)
  }

  redraw() {
    const chart = this.element.querySelector(".chart")
    if (chart && this.wide) this.draw(chart, this.wide)
  }

  extent(values, mid, share, floorAtZero) {
    const finiteValues = values.filter((v) => v != null && Number.isFinite(v))
    if (!finiteValues.length) return [0, 1]

    let lo = Math.min(...finiteValues)
    let hi = Math.max(...finiteValues)
    if (mid != null) {
      lo = Math.min(lo, mid)
      hi = Math.max(hi, mid)
    }
    if (hi === lo) {
      hi += 1
      lo -= 1
    }
    const padding = (hi - lo) * share
    return [floorAtZero && lo >= 0 ? Math.max(0, lo - padding) : lo - padding, hi + padding]
  }

  yTick(v) {
    return this.yPctValue ? `${Math.round(v)}%` : axisLabel(v)
  }

  format(v, pct) {
    if (v == null) return "n/a"
    return pct ? `${Number(v).toFixed(1)}%` : F(v)
  }

  fullWindow() {
    const points = this.pointsValue
    const xMid = this.hasXMidValue ? this.scaleX(this.xMidValue) : null
    const yMid = this.hasYMidValue ? this.yMidValue : null
    return {
      x: this.extent(points.map((p) => this.scaleX(p.x)), xMid, 0.08, !this.logX),
      y: this.extent(points.map((p) => Number(p.y)), yMid, 0.16, true)
    }
  }

  currentWindow() {
    const window = this.viewValue.window
    const valid = window && Array.isArray(window.x) && Array.isArray(window.y) &&
      window.x[1] > window.x[0] && window.y[1] > window.y[0]
    return valid ? window : this.fullWindow()
  }

  zoomable() {
    return this.hasViewValue && this.pointsValue.length > 1
  }

  isFullWindow(window) {
    if (!window) return true

    const full = this.fullWindow()
    const approxEqual = (a, b, span) => Math.abs(a - b) <= span * 1e-4
    const xSpan = full.x[1] - full.x[0]
    const ySpan = full.y[1] - full.y[0]
    return approxEqual(window.x[0], full.x[0], xSpan) && approxEqual(window.x[1], full.x[1], xSpan) &&
      approxEqual(window.y[0], full.y[0], ySpan) && approxEqual(window.y[1], full.y[1], ySpan)
  }

  canZoomIn(window) {
    const full = this.fullWindow()
    const current = window || full
    return current.x[1] - current.x[0] > (full.x[1] - full.x[0]) * MIN_ZOOM_FRACTION
  }

  windowCenter(window) {
    const current = window || this.fullWindow()
    return { x: (current.x[0] + current.x[1]) / 2, y: (current.y[0] + current.y[1]) / 2 }
  }

  zoomWindowAt(window, factor, anchor) {
    const full = this.fullWindow()
    const current = window || full
    const center = anchor || this.windowCenter(current)
    const zoomAxis = (range, limits, at) => {
      const span = range[1] - range[0]
      const limit = limits[1] - limits[0]
      const next = clamp(span * factor, limit * MIN_ZOOM_FRACTION, limit)
      const start = clamp(at - (at - range[0]) * (next / span), limits[0], limits[1] - next)
      return [start, start + next]
    }
    return { x: zoomAxis(current.x, full.x, center.x), y: zoomAxis(current.y, full.y, center.y) }
  }

  panWindow(window, dx, dy) {
    const g = this.geom
    if (!g || !window) return window

    const full = this.fullWindow()
    const shiftAxis = (range, limits, offset) => {
      const span = range[1] - range[0]
      const start = clamp(range[0] + offset, limits[0], limits[1] - span)
      return [start, start + span]
    }
    const xSpan = window.x[1] - window.x[0]
    const ySpan = window.y[1] - window.y[0]
    return {
      x: shiftAxis(window.x, full.x, (-dx / (g.plotRight - g.plotLeft)) * xSpan),
      y: shiftAxis(window.y, full.y, (dy / (g.plotBottom - g.plotTop)) * ySpan)
    }
  }

  windowFromSelection(from, to) {
    const g = this.geom
    if (!g || !from || !to) return null

    const wideEnough = Math.abs(g.x(to.x) - g.x(from.x)) >= MIN_SELECTION_PIXELS
    const tallEnough = Math.abs(g.y(to.y) - g.y(from.y)) >= MIN_SELECTION_PIXELS
    if (!wideEnough && !tallEnough) return null

    const current = this.currentWindow()
    return {
      x: wideEnough ? [Math.min(from.x, to.x), Math.max(from.x, to.x)] : current.x,
      y: tallEnough ? [Math.min(from.y, to.y), Math.max(from.y, to.y)] : current.y
    }
  }

  interpolateWindow(from, to, progress) {
    const mix = (a, b) => [a[0] + (b[0] - a[0]) * progress, a[1] + (b[1] - a[1]) * progress]
    return { x: mix(from.x, to.x), y: mix(from.y, to.y) }
  }

  anchorAt(event) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    return {
      x: g.x.invert(clamp(event.clientX - box.left, g.plotLeft, g.plotRight)),
      y: g.y.invert(clamp(event.clientY - box.top, g.plotTop, g.plotBottom))
    }
  }

  previewSelection(from, to) {
    const g = this.geom
    const area = this.element.querySelector(".selection-area")
    if (!g || !area || !from || !to) return

    const left = Math.min(g.x(from.x), g.x(to.x))
    const right = Math.max(g.x(from.x), g.x(to.x))
    const top = Math.min(g.y(from.y), g.y(to.y))
    const bottom = Math.max(g.y(from.y), g.y(to.y))
    area.setAttribute("x", left.toFixed(1))
    area.setAttribute("y", top.toFixed(1))
    area.setAttribute("width", (right - left).toFixed(1))
    area.setAttribute("height", (bottom - top).toFixed(1))
    area.removeAttribute("display")
  }

  inWindow(point, window) {
    const x = this.scaleX(point.x)
    return x >= window.x[0] && x <= window.x[1] && point.y >= window.y[0] && point.y <= window.y[1]
  }

  visibleIndices(window = this.currentWindow()) {
    const hidden = this.hiddenGroups
    return this.pointsValue
      .map((point, index) => ({ point, index }))
      .filter(({ point }) => !hidden.has(groupKey(point)) && this.inWindow(point, window))
      .map(({ index }) => index)
  }

  pointKey(index) {
    const point = this.pointsValue[index]
    return point ? String(point.name) : null
  }

  indexOfKey(key) {
    return this.pointsValue.findIndex((point) => String(point.name) === key)
  }

  windowLabel(window) {
    const visibleCount = this.visibleIndices(window).length
    return { label: "Zoomed", detail: `${visibleCount} of ${this.pointsValue.length}` }
  }

  groups() {
    const groupsByKey = new Map()
    this.pointsValue.forEach((point) => {
      const key = groupKey(point)
      if (!groupsByKey.has(key)) groupsByKey.set(key, { key, seriesColor: point.seriesColor == null ? 1 : point.seriesColor, label: point.phase || "points" })
    })
    return [...groupsByKey.values()].sort((a, b) => a.seriesColor - b.seriesColor)
  }

  legendEntries() {
    return this.groups().map((group) => ({
      key: group.key, label: group.label, colorClass: `ser-${group.seriesColor}`, color: null, shape: "dot"
    }))
  }

  displayDefaults() {
    return { grid: true, notes: true, labels: true, xScale: "linear" }
  }

  displayOptions() {
    return {
      grid: true,
      notes: this.hasNotes,
      labels: true,
      xScale: this.pointsValue.every((point) => Number(point.x) > 0)
    }
  }

  pointDetails(i) {
    const point = this.pointsValue[i]
    if (!point) return null

    const colorClass = `ser-${point.seriesColor == null ? 1 : point.seriesColor}`
    const value = (label, text) => ({ label, colorClass, color: null, shape: "dot", value: text, change: null, share: null })
    return {
      title: `#${point.name}`,
      qualifier: point.phase || null,
      tags: [],
      note: null,
      total: null,
      values: [
        this.xLabelValue && value(this.xLabelValue, this.format(point.x, false)),
        this.yLabelValue && value(this.yLabelValue, this.format(point.y, this.yPctValue)),
        this.nLabelValue && value(this.nLabelValue, F(point.n))
      ].filter(Boolean)
    }
  }

  rangeStats(window) {
    const points = this.visibleIndices(window || this.currentWindow()).map((index) => this.pointsValue[index])
    const total = this.pointsValue.length
    const sum = points.reduce((at, point) => at + (Number(point.n) || 0), 0)
    return {
      summary: [
        { label: "channels", value: `${points.length} of ${total}` },
        this.xLabelValue && { label: `median ${this.xLabelValue}`, value: this.format(median(points.map((p) => p.x)), false) },
        this.yLabelValue && { label: `median ${this.yLabelValue}`, value: this.format(median(points.map((p) => p.y)), this.yPctValue) },
        this.nLabelValue && { label: this.nLabelValue, value: F(sum) }
      ].filter(Boolean)
    }
  }

  tableData(window) {
    const indices = this.visibleIndices(window || this.currentWindow())
      .sort((a, b) => (Number(this.pointsValue[b].n) || 0) - (Number(this.pointsValue[a].n) || 0))
    const columns = [
      { key: "label", label: "Channel", numeric: false },
      { key: "x", label: this.xLabelValue || "x", numeric: true },
      { key: "y", label: this.yLabelValue || "y", numeric: true },
      { key: "n", label: this.nLabelValue || "n", numeric: true },
      { key: "group", label: "Group", numeric: false }
    ]
    const rows = indices.map((index) => {
      const point = this.pointsValue[index]
      return {
        index,
        values: { label: point.name, x: Number(point.x), y: Number(point.y), n: Number(point.n), group: point.phase || null },
        display: {
          label: `#${point.name}`, x: this.format(point.x, false), y: this.format(point.y, this.yPctValue),
          n: F(point.n), group: point.phase || ""
        },
        note: null
      }
    })
    return { columns, rows, footer: null }
  }

  draw(chart, wide) {
    const points = this.pointsValue
    if (!points.length) return

    const high = this.high
    const window = this.currentWindow()
    const plotLeft = PAD.left
    const plotRight = wide - PAD.right
    const plotTop = PAD.top
    const plotBottom = high - PAD.bottom
    const xMid = this.hasXMidValue ? this.xMidValue : null
    const yMid = this.hasYMidValue ? this.yMidValue : null

    const x = scaleLinear().domain(window.x).range([plotLeft, plotRight])
    const y = scaleLinear().domain(window.y).range([plotBottom, plotTop])
    const r = scaleSqrt().domain([0, Math.max(1, ...points.map((p) => Number(p.n) || 0))])
      .range(this.hasViewValue ? EXPLORER_RADIUS : CARD_RADIUS)
    const at = (point) => [x(this.scaleX(point.x)), y(Number(point.y))]

    const yTicks = y.ticks(high > 400 ? 6 : 4)
    const grid = yTicks.map((v) =>
      (this.showGrid
        ? `<line class="grid" x1="${plotLeft}" y1="${y(v).toFixed(1)}" x2="${plotRight}" y2="${y(v).toFixed(1)}"/>`
        : "") +
      `<text class="ax" x="${plotLeft - 7}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${
        this.yTick(v)}</text>`).join("")

    const xTicks = this.logX
      ? logTicks(Math.max(1, 10 ** window.x[0]), 10 ** window.x[1]).map((v) => [Math.log10(v), v])
      : x.ticks(Math.max(2, Math.floor((plotRight - plotLeft) / 76))).map((v) => [v, v])
    const xTickLabels = xTicks
      .filter(([position]) => x(position) >= plotLeft - 1 && x(position) <= plotRight + 1)
      .map(([position, v]) => `<text class="ax" x="${x(position).toFixed(1)}" y="${plotBottom + 22}" text-anchor="middle">${
        axisLabel(v)}</text>`).join("")

    const midLines = this.showNotes ? [
      xMid == null ? "" : `<line class="mark-rule" x1="${x(this.scaleX(xMid)).toFixed(1)}" y1="${
        plotTop}" x2="${x(this.scaleX(xMid)).toFixed(1)}" y2="${plotBottom.toFixed(1)}"/>`,
      yMid == null ? "" : `<line class="mark-rule" x1="${plotLeft}" y1="${
        y(yMid).toFixed(1)}" x2="${plotRight}" y2="${y(yMid).toFixed(1)}"/>`
    ].join("") : ""

    const cornerLabels = this.hasCornersValue && this.showNotes ? this.cornersValue : {}
    const corners = CORNERS.map((corner) => {
      const label = cornerLabels[corner]
      if (!label) return ""

      const left = corner[1] === "l"
      const top = corner[0] === "t"
      return `<text class="ax quad-note" x="${
        (left ? plotLeft + 6 : plotRight - 6).toFixed(1)}" y="${
        (top ? plotTop + 11 : plotBottom - 6).toFixed(1)}" text-anchor="${
        left ? "start" : "end"}">${esc(label)}</text>`
    }).join("")

    const hidden = this.hiddenGroups
    const visible = points
      .map((point, index) => ({ point, index }))
      .filter(({ point }) => !hidden.has(groupKey(point)))
      .filter(({ point }) => {
        const [cx, cy] = at(point)
        const radius = r(Number(point.n) || 0)
        return cx >= plotLeft - radius && cx <= plotRight + radius && cy >= plotTop - radius && cy <= plotBottom + radius
      })
      .sort((a, b) => (Number(b.point.n) || 0) - (Number(a.point.n) || 0))

    const dots = visible.map(({ point, index }) => {
      const [cx, cy] = at(point)
      return `<circle class="scatter-point ser-${point.seriesColor == null ? 1 : point.seriesColor}" data-i="${index}" data-series="${
        groupKey(point)}" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r(Number(point.n) || 0).toFixed(1)}"/>`
    }).join("")

    const pin = this.viewValue.pin
    const pinned = visible.find(({ index }) => index === pin)
    const pinOutline = pinned
      ? (() => {
        const [cx, cy] = at(pinned.point)
        return `<circle class="pin-ring" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${
          (r(Number(pinned.point.n) || 0) + 4).toFixed(1)}"/>`
      })()
      : ""
    const labels = this.pointLabels(visible, pinned, { at, r, plotRight })

    const caption = this.xLabelValue
      ? `<text class="ax cap-note" x="${((plotLeft + plotRight) / 2).toFixed(1)}" y="${
        high - X_TITLE_INSET}" text-anchor="middle">${esc(this.xLabelValue)}${this.logX ? ", log scale" : ""}</text>`
      : ""

    const yTitle = this.yLabelValue
      ? `<text class="ax cap-note" transform="translate(${Y_TITLE_INSET},${
        ((plotTop + plotBottom) / 2).toFixed(1)}) rotate(-90)" text-anchor="middle">${
        esc(this.yLabelValue)}</text>`
      : ""

    const selection = this.externalPointer ? '<rect class="selection-area" display="none"/>' : ""
    const clipId = `${this.gid}-clip`
    const clipPath = `<clipPath id="${clipId}"><rect x="${plotLeft}" y="${plotTop - 4}" width="${
      (plotRight - plotLeft).toFixed(1)}" height="${(plotBottom - plotTop + 8).toFixed(1)}"/></clipPath>`

    chart.querySelector("svg")?.remove()
    chart.insertAdjacentHTML("afterbegin",
      `<svg width="${wide}" height="${high}" viewBox="0 0 ${wide} ${high}" role="img"
        aria-label="${esc(this.summary(visible.map(({ point }) => point)))}"><defs>${clipPath}</defs>${grid}` +
      `<line class="base" x1="${plotLeft}" y1="${plotBottom.toFixed(1)}" x2="${
        plotRight}" y2="${plotBottom.toFixed(1)}"/>` +
      `<g clip-path="url(#${clipId})">${midLines}${dots}${pinOutline}${labels}</g>${corners}${xTickLabels}${caption}${yTitle}${
        selection}</svg>`)

    this.geom = { x, y, r, at, wide, high, plotLeft, plotRight, plotTop, plotBottom, visible: visible.map(({ index }) => index) }
    if (this.at != null) {
      if (this.geom.visible.includes(this.at)) this.show(this.at, { silent: true })
      else this.clear()
    }
  }

  pointLabels(visible, pinned, { at, r, plotRight }) {
    if (!this.showLabels && !pinned) return ""

    const labelCandidates = this.showLabels ? (visible.length <= LABEL_LIMIT ? visible : visible.slice(0, LABEL_TOP)) : []
    const ordered = pinned && !labelCandidates.includes(pinned) ? [pinned, ...labelCandidates] : labelCandidates
    const occupiedBoxes = []
    return ordered.map(({ point, index }) => {
      const [cx, cy] = at(point)
      const radius = r(Number(point.n) || 0)
      const text = `#${point.name}`
      const width = text.length * 6.6
      const flip = cx + radius + 6 + width > plotRight
      const left = flip ? cx - radius - 5 - width : cx + radius + 5
      const box = { left: left - 2, right: left + width + 2, top: cy - 8, bottom: cy + 8 }
      const overlaps = occupiedBoxes.some((other) =>
        box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)
      if (overlaps && index !== pinned?.index) return ""

      occupiedBoxes.push(box)
      return `<text class="point-label" data-series="${groupKey(point)}" x="${left.toFixed(1)}" y="${(cy + 4).toFixed(1)}">${
        esc(text)}</text>`
    }).join("")
  }

  summary(points = this.pointsValue) {
    if (!points.length) return "No channels in view"

    const best = points.reduce((top, p) => (p.y > top.y ? p : top), points[0])
    const worst = points.reduce((low, p) => (p.y < low.y ? p : low), points[0])
    return `${points.length} channels by ${this.xLabelValue || "x"} against ${
      this.yLabelValue || "y"}, from ${worst.name} at ${
      this.format(worst.y, this.yPctValue)} to ${best.name} at ${this.format(best.y, this.yPctValue)}`
  }

  indexAtPointer(event) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    const mx = event.clientX - box.left
    const my = event.clientY - box.top
    let nearestIndex = null
    let nearestGap = Infinity
    g.visible.forEach((index) => {
      const point = this.pointsValue[index]
      const [cx, cy] = g.at(point)
      const gap = Math.hypot(cx - mx, cy - my) - g.r(Number(point.n) || 0)
      if (gap < nearestGap) {
        nearestGap = gap
        nearestIndex = index
      }
    })
    return nearestIndex != null && nearestGap <= HIT_DISTANCE ? nearestIndex : null
  }

  track(event) {
    const i = this.indexAtPointer(event)
    if (i == null) return this.clear()

    this.show(i)
  }

  key(event) {
    const g = this.geom
    if (!g) return

    const order = [...g.visible].sort((a, b) => this.pointsValue[a].x - this.pointsValue[b].x)
    if (!order.length) return

    const last = order.length - 1
    const position = order.indexOf(this.at)
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    let next
    if (step) next = position < 0 ? (step > 0 ? 0 : last) : clamp(position + step, 0, last)
    else if (event.key === "Home") next = 0
    else if (event.key === "End") next = last
    else if (event.key === "Escape") return this.clear()
    else return

    event.preventDefault()
    this.show(order[next], { source: "keyboard" })
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
    const chart = this.element.querySelector(".chart")
    const p = this.pointsValue[i]
    if (!g || !p) return

    this.at = i
    if (!silent) this.announcePoint(i, source)
    chart.querySelectorAll(".scatter-point").forEach((dot) =>
      dot.classList.toggle("lit", Number(dot.dataset.i) === i))

    const rows = [
      [this.xLabelValue, this.format(p.x, false), p.seriesColor],
      [this.yLabelValue, this.format(p.y, this.yPctValue), p.seriesColor],
      [this.nLabelValue, F(p.n), 0]
    ].filter(([label]) => label)

    const tip = chart.querySelector(".tip")
    tip.innerHTML = `<div class="t">#${esc(p.name)}${
      p.phase ? ` <span class="t-note">${esc(p.phase)}</span>` : ""}</div>` +
      rows.map(([label, value, seriesColor]) =>
        `<div class="row"><i class="ser-${seriesColor == null ? 1 : seriesColor}"></i>${
          esc(label)}<b>${value}</b></div>`).join("")
    tip.classList.add("on")

    const [cx, cy] = g.at(p)
    const tipWide = tip.offsetWidth || 190
    let left = cx + 16
    if (left + tipWide > g.wide) left = cx - 16 - tipWide
    tip.style.left = `${Math.max(0, left)}px`
    tip.style.top = `${Math.max(PAD.top, Math.min(cy - 12, g.high - 110))}px`

    chart.querySelector(".chart-caption").textContent =
      `${p.name}, ${this.xLabelValue} ${this.format(p.x, false)}, ${
        this.yLabelValue} ${this.format(p.y, this.yPctValue)}`
  }

  clear() {
    const chart = this.element.querySelector(".chart")
    if (!chart) return

    this.at = null
    this.announcePoint(null, "pointer")
    chart.querySelectorAll(".scatter-point.lit").forEach((dot) => dot.classList.remove("lit"))
    chart.querySelector(".tip")?.classList.remove("on")
    chart.querySelector(".selection-area")?.setAttribute("display", "none")
    const caption = chart.querySelector(".chart-caption")
    if (caption) caption.textContent = ""
  }
}
