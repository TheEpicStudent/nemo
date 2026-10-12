import { Controller } from "@hotwired/stimulus"
import { scaleBand, scaleLinear, scaleLog } from "d3-scale"
import { line as lineOf, area as areaOf, curveMonotoneX, curveLinear } from "d3-shape"
import {
  clampWindow, isFullWindow, zoomWindow, shiftWindow, windowAround, interpolateWindow, minimumSpan, MIN_WINDOW_ROWS
} from "charts/frame"

let seq = 0

const SERIES_COLORS = [1, 2, 3, 4, 5, 0]

const PAD = { l: 44, r: 8, t: 20, b: 34 }

const BAR_CAP = 72
const BAR_R = 6
const PILL_H = 22
const SEG_GAP = 2
const X_TITLE_SPACE = 26
const Y_TITLE_SPACE = 22

const MEASURE_CTX = typeof document === "undefined"
  ? null
  : document.createElement("canvas").getContext("2d")

function axisTextWidth(text) {
  if (!MEASURE_CTX) return String(text).length * 6

  MEASURE_CTX.font = '12px Geist, ui-sans-serif, system-ui, sans-serif'
  return MEASURE_CTX.measureText(String(text)).width
}

const BIN = /^([<>])?(\d+)(?:-(\d+))?(\+)?$/

const kilo = (n) => (n >= 1000 ? `${+(n / 1000).toFixed(n % 1000 >= 100 ? 1 : 0)}k` : String(n))

function binLabels(rows) {
  const parts = rows.map((r) => BIN.exec(String(r.label)))
  if (!parts.length || parts.some((m) => !m)) return null

  const ranged = parts.map(([, side, a, b, plus]) =>
    `${side || ""}${kilo(Number(a))}${b ? `-${kilo(Number(b))}` : ""}${plus ? "+" : ""}`)
  const lowerBounds = parts.map(([, side, a, , plus]) => `${side || ""}${kilo(Number(a))}${plus ? "+" : ""}`)
  return [ranged, lowerBounds]
}

const F = (n) => (n == null ? "n/a" : Number(n).toLocaleString("en-US"))

const LOG_MANTISSAS = [1, 2, 5]

function logTicks(lo, hi) {
  const decades = []
  const steps = []
  for (let exp = Math.floor(Math.log10(lo)); exp <= Math.ceil(Math.log10(hi)); exp++) {
    LOG_MANTISSAS.forEach((m) => {
      const v = m * 10 ** exp
      if (v >= lo * 0.999 && v <= hi * 1.001) (m === 1 ? decades : steps).push(v)
    })
  }
  return decades.length >= 3 ? decades : [...decades, ...steps].sort((a, b) => a - b)
}

const axisLabel = (v) =>
  Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `${Math.round(v)}`

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi)

const withoutViewport = ({ window: _window, pin: _pin, ...view }) => JSON.stringify(view)
const sameExceptViewport = (value, previous) => withoutViewport(value) === withoutViewport(previous)
const WEEKEND = [0, 6]
const MIN_SELECTION_ROWS = 2

function dayLabel(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric", timeZone: "UTC"
  })
}

function dayTitle(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC"
  })
}

function topBar(x, y, w, h, r) {
  if (!(h > 0) || !(w > 0)) return ""

  const k = Math.min(r, w / 2, h / 2)
  return `M${x},${y + h}V${y + k}a${k},${k} 0 0 1 ${k},${-k}h${w - 2 * k}a${k},${k} 0 0 1 ${k},${k}V${y + h}Z`
}

const ISO = /^\d{4}-\d{2}-\d{2}$/

function dayStep(iso, n) {
  const at = new Date(`${iso}T00:00:00Z`)
  at.setUTCDate(at.getUTCDate() + n)
  return at.toISOString().slice(0, 10)
}

function daySpan(from, to) {
  const out = []
  for (let at = from; at <= to; at = dayStep(at, 1)) out.push(at)
  return out
}

function dayName(iso) {
  const at = new Date(`${iso}T00:00:00Z`)
  return `${at.toLocaleString("en-US", { month: "short", timeZone: "UTC" })} ${at.getUTCDate()}`
}

export default class extends Controller {
  static values = {
    kind: String, data: Object, height: Number, pct: Boolean, pctFit: Boolean,
    stacked: Boolean, days: Boolean, spark: Boolean, rule: Object, splits: Array,
    voids: Array, partial: Array, partialNote: String, notes: Array, caps: Array, nokey: Boolean,
    xlabel: String, ylabel: String, brush: Boolean, brushHref: String, brushKeys: Array,
    view: Object
  }

  connect() {
    this.gid = `cg${++seq}`
    this.defaultKind = this.kindValue || "bars"
    this.at = null
    this.wide = 0
    this.observer = new ResizeObserver(() => this.measure())
    this.build()
    this.ready = true
    if (this.hasViewValue) this.dispatch("ready")
  }

  disconnect() {
    this.ready = false
    this.observer?.disconnect()
  }

  viewValueChanged(value, previous) {
    if (!this.ready) return
    if (previous && sameExceptViewport(value, previous)) {
      this.redraw()
      return
    }

    this.build({ animate: false })
    this.dispatch("update")
  }

  redraw() {
    const chart = this.element.querySelector(".chart")
    if (!chart || !this.wide) {
      this.build({ animate: false })
      return
    }
    this.draw(chart, this.wide)
  }

  get externalPointer() {
    return this.viewValue.pointer === "external"
  }

  rowCount() {
    return this.rows.length
  }

  unitAt(event) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    const offset = (event.clientX - box.left - g.x.range()[0]) / g.x.step() - g.x.paddingOuter() / 2
    return clamp(offset, 0, g.rows.length)
  }

  rowSpan(window, count) {
    const last = count - 1
    const [start, end] = window || [0, count]
    const first = clamp(Math.floor(start), 0, last)
    return [first, clamp(Math.ceil(end) - 1, first, last)]
  }

  rangeStats(window) {
    const rows = this.rows
    if (!rows.length) return null

    const [first, final] = this.rowSpan(window, rows.length)
    const span = final - first + 1
    const before = first - span >= 0 ? [first - span, first - 1] : null
    const pointsOf = (s, from, to) => rows.slice(from, to + 1)
      .map((r, k) => ({ index: from + k, value: r.gap || r[s.k] == null ? null : Number(r[s.k]) }))
      .filter((point) => point.value != null)
    const summarize = (points) => {
      const sum = points.reduce((at, point) => at + point.value, 0)
      return { sum, mean: sum / points.length }
    }

    return {
      percent: this.pctValue,
      fromLabel: rows[first].label,
      toLabel: rows[final].label,
      hasPrevious: !!before,
      series: this.series.filter((s) => !s.ghost).map((s) => {
        const points = pointsOf(s, first, final)
        const entry = { label: s.n, colorClass: this.seriesClass(s), color: s.own || null, shape: this.shapeOf(s) }
        if (!points.length) return { ...entry, empty: true }

        const { sum, mean } = summarize(points)
        const max = points.reduce((best, point) => (point.value > best.value ? point : best))
        const min = points.reduce((best, point) => (point.value < best.value ? point : best))
        const previous = before ? pointsOf(s, before[0], before[1]) : []
        const prior = previous.length ? summarize(previous) : null
        let change = null
        if (prior && this.pctValue) change = { value: mean - prior.mean, unit: "pts" }
        else if (prior && prior.sum) change = { value: ((sum - prior.sum) / Math.abs(prior.sum)) * 100, unit: "%" }

        return {
          ...entry,
          total: this.format(sum),
          mean: this.format(this.pctValue ? mean : Math.round(mean)),
          max: { index: max.index, value: this.format(max.value) },
          min: { index: min.index, value: this.format(min.value) },
          change
        }
      })
    }
  }

  tableData(window) {
    const rows = this.rows
    if (!rows.length) return null

    const [first, final] = this.rowSpan(window, rows.length)
    const series = this.series
    const solid = series.filter((s) => !s.ghost && !s.over)
    const stacked = this.stack
    const dated = this.daysValue
    const label = { key: "label", label: dated ? "Day" : this.xlabelValue || "", numeric: false }
    const columns = [
      label,
      ...series.map((s) => ({
        key: s.k, label: s.n, numeric: true, colorClass: this.seriesClass(s), color: s.own || null, shape: this.shapeOf(s)
      })),
      ...(stacked ? [{ key: "total", label: "total", numeric: true }] : [])
    ]
    const partial = new Set(this.hasPartialValue ? this.partialValue.map(Number) : [])
    const body = rows.slice(first, final + 1).map((row, offset) => {
      const index = first + offset
      const values = { label: dated && ISO.test(row.key) ? row.key : row.label }
      const display = { label: dated && ISO.test(row.key) ? dayLabel(row.key) : row.label }
      series.forEach((s) => {
        values[s.k] = row.gap || row[s.k] == null ? null : Number(row[s.k])
        display[s.k] = this.format(values[s.k])
      })
      if (stacked) {
        values.total = row.gap ? null : this.sum(row, solid)
        display.total = this.format(values.total)
      }
      const note = row.gap ? row.why || "not fetched" : partial.has(index) ? this.partialNoteValue || "period not complete" : null
      return { index, values, display, note }
    })
    const footerValues = {}
    columns.filter((column) => column.numeric).forEach((column) => {
      const present = body.map((row) => row.values[column.key]).filter((value) => value != null)
      if (!present.length) return
      const sum = present.reduce((at, value) => at + value, 0)
      footerValues[column.key] = this.format(this.pctValue ? sum / present.length : sum)
    })
    return { columns, rows: body, footer: { label: this.pctValue ? "Mean" : "Total", values: footerValues } }
  }

  rangeOf(window) {
    const rows = this.rows
    if (!rows.length) return null

    const [first, final] = this.rowSpan(window, rows.length)
    return {
      from: String(rows[first].key), to: String(rows[final].key),
      fromLabel: rows[first].label, toLabel: rows[final].label, first, last: final,
      count: final - first + 1, total: rows.length, daily: this.daysValue
    }
  }

  pointKey(index) {
    const row = this.rows[index]
    return row ? String(row.key) : null
  }

  indexOfKey(key) {
    return this.rows.findIndex((row) => String(row.key) === key)
  }

  windowForKeys(from, to) {
    const rows = this.rows
    const start = rows.findIndex((r) => String(r.key) === from)
    const end = rows.findIndex((r) => String(r.key) === to)
    if (start < 0 || end < start) return null

    return [start, end + 1]
  }

  plotBounds() {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    return { left: box.left + g.pad.l, right: box.right - g.pad.r }
  }

  overviewSeries() {
    const rows = this.rows
    const visible = this.series.filter((s) => !s.ghost && !s.over)
    if (!this.line) {
      return { kind: "bars", values: rows.map((r) => (r.gap ? 0 : this.sum(r, visible))) }
    }
    return {
      kind: "line",
      lines: visible.map((s) => ({
        colorClass: this.seriesClass(s), color: s.own || null,
        values: rows.map((r) => (r[s.k] == null ? null : Number(r[s.k])))
      }))
    }
  }

  rowsPerPixel() {
    return this.geom ? 1 / this.geom.x.step() : 0
  }

  selectUnits(from, to) {
    const g = this.geom
    if (!g) return

    const last = g.rows.length - 1
    const lo = clamp(Math.floor(Math.min(from, to)), 0, last)
    const hi = clamp(Math.ceil(Math.max(from, to)) - 1, lo, last)
    this.highlightRows(lo, hi)
  }

  zoomable() {
    return !this.sparkValue && this.rowCount() > MIN_WINDOW_ROWS
  }

  fullWindow() {
    return [0, this.rowCount()]
  }

  isFullWindow(window) {
    return isFullWindow(window, this.rowCount())
  }

  canZoomIn(window) {
    const [start, end] = window || this.fullWindow()
    return end - start > minimumSpan(this.rowCount()) + 0.001
  }

  windowCenter(window) {
    const [start, end] = window || this.fullWindow()
    return (start + end) / 2
  }

  zoomWindowAt(window, factor, anchor) {
    return zoomWindow(window || this.fullWindow(), this.rowCount(), factor, anchor ?? this.windowCenter(window))
  }

  panWindow(window, dx) {
    return shiftWindow(window || this.fullWindow(), this.rowCount(), -dx * this.rowsPerPixel())
  }

  windowFromSelection(from, to) {
    if (from == null || to == null) return null

    const start = Math.floor(Math.min(from, to))
    const end = Math.ceil(Math.max(from, to))
    if (end - start < MIN_SELECTION_ROWS) return null

    return windowAround(start, end, this.rowCount())
  }

  interpolateWindow(from, to, progress) {
    return interpolateWindow(from, to, progress)
  }

  anchorAt(event) {
    return this.unitAt(event)
  }

  previewSelection(from, to) {
    if (from != null && to != null) this.selectUnits(from, to)
  }

  windowLabel(window) {
    const range = this.rangeOf(window)
    if (!range) return null

    return {
      label: range.from === range.to ? range.fromLabel : `${range.fromLabel} to ${range.toLabel}`,
      detail: range.daily ? `${range.count} ${range.count === 1 ? "day" : "days"}` : `${range.count} of ${range.total}`
    }
  }

  windowFor(count) {
    const window = this.viewValue.window
    if (!Array.isArray(window) || count < 2) return null

    const clamped = clampWindow(window.map(Number), count, 1)
    return isFullWindow(clamped, count) ? null : clamped
  }

  visibleRange(count) {
    const window = this.windowFor(count)
    if (!window) return [0, count - 1]

    const first = clamp(Math.floor(window[0]), 0, count - 1)
    return [first, clamp(Math.ceil(window[1]) - 1, first, count - 1)]
  }

  get rows() {
    const { labels = [], datasets = [] } = this.dataValue
    const voidNotes = new Map((this.hasVoidsValue ? this.voidsValue : [])
      .map((v) => [Number(v.at), v.note || ""]))
    const notes = this.hasNotesValue ? this.notesValue : []
    const baseRows = labels.map((label, i) => {
      const key = Array.isArray(label) ? label[0] : label
      const row = { label: key, key }
      datasets.forEach((set, s) => {
        row[`s${s}`] = set.data[i]
        if (set.counts) row[`c${s}`] = set.counts[i]
      })
      if (notes[i]) row.tip = notes[i]
      if (voidNotes.has(i)) {
        row.gap = true
        row.why = voidNotes.get(i)
      }
      return row
    })
    if (!this.daysValue || !baseRows.length) return baseRows

    const dated = baseRows.filter((row) => ISO.test(row.key))
    if (dated.length < 2) return baseRows

    const rowsByKey = new Map(dated.map((row) => [row.key, row]))
    const keys = dated.map((row) => row.key).sort()
    return daySpan(keys[0], keys[keys.length - 1]).map((day) => {
      const row = rowsByKey.get(day)
      if (row) return { ...row, label: dayName(day) }

      const gap = { label: dayName(day), key: day, gap: true }
      datasets.forEach((_, s) => { gap[`s${s}`] = null; gap[`c${s}`] = null })
      return gap
    })
  }

  get allSeries() {
    return (this.dataValue.datasets || []).map((set, i) => ({
      k: `s${i}`, c: `c${i}`, n: set.label, seriesColor: SERIES_COLORS[i % SERIES_COLORS.length], own: set.color,
      ghost: !!set.ghost, over: !!set.over
    }))
  }

  get hiddenSeries() {
    return new Set(this.viewValue.hidden || [])
  }

  get series() {
    const hidden = this.hiddenSeries
    return this.allSeries.filter((s) => !hidden.has(s.k))
  }

  legendEntries() {
    const all = this.allSeries
    const order = this.stacked && !this.line ? all.slice().reverse() : all
    return order.map((s) => ({
      key: s.k, label: s.n, colorClass: this.seriesClass(s), color: s.own || null, shape: this.shapeOf(s)
    }))
  }

  shapeOf(s) {
    if (s.ghost) return "dashed"
    return this.line ? "line" : "box"
  }

  pointDetails(i) {
    const rows = this.rows
    const row = rows[i]
    if (!row) return null

    const previous = i > 0 ? rows[i - 1] : null
    const series = this.series
    const solid = series.filter((s) => !s.ghost && !s.over)
    const total = this.stack && !row.gap ? this.sum(row, solid) : null
    const dated = this.daysValue && ISO.test(row.key)
    const tags = []
    if (row.gap) tags.push(row.why || "not fetched")
    if (this.hasPartialValue && this.partialValue.map(Number).includes(i)) {
      tags.push(this.partialNoteValue || "period not complete")
    }

    return {
      title: dated ? dayTitle(row.key) : row.label,
      qualifier: dated && WEEKEND.includes(new Date(`${row.key}T00:00:00Z`).getUTCDay()) ? "weekend" : null,
      tags,
      note: row.tip || null,
      total: total == null ? null : this.format(total),
      values: series.map((s) => ({
        label: s.n, colorClass: this.seriesClass(s), color: s.own || null, shape: this.shapeOf(s),
        value: row.gap ? "n/a" : this.format(row[s.k]),
        change: this.changeFrom(previous, row, s),
        share: total && solid.includes(s) && row[s.k] != null ? `${((row[s.k] / total) * 100).toFixed(1)}%` : null
      }))
    }
  }

  changeFrom(previous, row, s) {
    if (!previous || previous.gap || row.gap) return null

    const now = row[s.k]
    const before = previous[s.k]
    if (now == null || before == null) return null
    if (this.pctValue) return { value: Number(now) - Number(before), unit: "pts" }
    if (!Number(before)) return null

    return { value: ((Number(now) - Number(before)) / Math.abs(Number(before))) * 100, unit: "%" }
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
    this.dispatch("point", { detail: { index, source } })
  }

  get fill() {
    return !!this.viewValue.fill
  }

  get height() {
    if (this.fill && this.fillHeight > 0) return this.fillHeight
    return this.hasHeightValue && this.heightValue > 0 ? this.heightValue : 214
  }

  get line() {
    return (this.viewValue.kind || this.defaultKind) === "line"
  }

  get stacked() {
    return this.viewValue.stacked ?? this.stackedValue
  }

  get pctFit() {
    return this.viewValue.fit ?? this.pctFitValue
  }

  get logScale() {
    return this.line && this.viewValue.yScale === "log" && !this.pctValue
  }

  get showGrid() {
    return this.viewValue.grid !== false
  }

  get showNotes() {
    return this.viewValue.notes !== false
  }

  get hasNotes() {
    return (this.hasRuleValue && this.ruleValue.at != null) ||
      (this.hasSplitsValue && this.splitsValue.length > 0) ||
      (this.hasPartialValue && this.partialValue.length > 0) || this.daysValue
  }

  displayDefaults() {
    return {
      kind: this.kindValue || "bars", stacked: this.stackedValue, fit: this.pctFitValue,
      yScale: "linear", zero: false, format: "full", grid: true, notes: true, overview: true
    }
  }

  displayOptions() {
    return {
      kind: true,
      stacked: this.allSeries.filter((s) => !s.ghost && !s.over).length > 1,
      yScale: !this.pctValue,
      zero: !this.pctValue,
      fit: this.pctValue,
      format: !this.pctValue,
      grid: true,
      notes: this.hasNotes,
      overview: this.zoomable()
    }
  }

  build({ animate = true } = {}) {
    const series = this.series
    const rows = this.rows
    if (!rows.length) return
    if (!series.length) {
      if (this.hasViewValue) this.element.innerHTML = '<div class="chart-empty">No series shown</div>'
      return
    }

    if (!this.sparkValue && rows.every((r) => series.every((s) => !Number(r[s.k])))) {
      this.element.innerHTML = `<div class="chart-empty" style="min-height:${this.height}px">Nothing in this range</div>`
      return
    }

    this.firstDraw = animate
    this.element.classList.toggle("chart-spark", this.sparkValue)
    const brush = this.brushValue
      ? " pointerdown->chart#press pointermove->chart#drag pointerup->chart#release pointercancel->chart#release"
      : ""
    const hover = this.externalPointer ? "" : "mousemove->chart#track mouseleave->chart#clear "
    this.element.innerHTML = `${this.head(series)}<div class="chart tipped${
      this.brushValue ? " is-brush" : ""}" tabindex="0"
      data-action="${hover}keydown->chart#key${brush}"
      ><div class="tip"></div><span class="chart-caption" aria-live="polite"></span></div>`
    this.wide = 0
    this.observer.disconnect()
    this.observer.observe(this.element.querySelector(".chart"))
    this.measure()
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

  head(series) {
    const swatch = (s) =>
      `<span><i class="${this.seriesClass(s)}${s.ghost ? " ghost" : ""}"${
        this.tint(s)}></i>${esc(s.n)}</span>`
    if (series.length < 2 || this.sparkValue || this.nokeyValue || this.viewValue.legend === false) return ""

    const order = this.stack ? series.slice().reverse() : series
    return `<div class="chart-legend">${order.map(swatch).join("")}</div>`
  }

  seriesClass(s) {
    return `ser-${s.seriesColor}`
  }

  tint(s) {
    return s.own ? ` style="color:${esc(s.own)}"` : ""
  }

  mark(s) {
    return `${this.tint(s)} data-series="${s.k}"`
  }

  tick(v) {
    if (!this.pctValue) return axisLabel(v)

    return this.fineTicks ? `${Number(v).toFixed(1)}%` : `${Math.round(v)}%`
  }

  format(v) {
    if (v == null) return "n/a"
    if (this.pctValue) return `${Number(v).toFixed(1)}%`
    return this.viewValue.format === "compact" ? axisLabel(v) : F(v)
  }

  get overlaySeries() {
    return this.line ? [] : this.series.filter((s) => s.over)
  }

  get pad() {
    if (this.sparkValue) return { l: 1, r: 1, t: 3, b: 3 }

    const text = {
      ...PAD,
      r: PAD.r + (this.overlaySeries.length ? 34 : 0),
      l: PAD.l + (this.xlabelValue || this.ylabelValue ? Y_TITLE_SPACE : 0),
      b: PAD.b + (this.xlabelValue ? X_TITLE_SPACE : 0)
    }
    return text
  }

  get stack() {
    return this.stacked && !this.line && this.series.filter((s) => !s.over).length > 1
  }

  sum(row, series) {
    return series.reduce((at, s) => at + (row[s.k] == null ? 0 : Number(row[s.k])), 0)
  }

  scales(rows, series, wide) {
    const high = this.height
    const line = this.line
    const pad = this.pad

    const padding = line ? 0 : 0.26
    const window = this.windowFor(rows.length)
    const [from, to] = window || [0, rows.length]
    const step = (wide - pad.r - pad.l) / (to - from + padding)
    const start = pad.l - from * step
    const x = scaleBand()
      .domain(rows.map((_, i) => i))
      .range([start, start + step * (rows.length + padding)])
      .padding(padding)

    const [first, last] = this.visibleRange(rows.length)
    const visible = rows.slice(first, last + 1)
    const visibleValues = this.stack
      ? visible.map((r) => this.sum(r, series))
      : visible.flatMap((r) => series.map((s) => r[s.k])).filter((v) => v != null)
    let lo = 0
    let hi = visibleValues.length ? Math.max(...visibleValues) : 0

    const pinned = this.pctValue && !this.pctFit
    const log = this.logScale
    if (pinned) {
      lo = 0
      hi = 100
    } else if (log) {
      const positive = visibleValues.map(Number).filter((v) => v > 0)
      lo = positive.length ? Math.min(...positive) : 1
      hi = Math.max(hi, lo * 2)
    } else if (line && visibleValues.length) {
      const least = Math.min(...visibleValues)
      if (this.sparkValue) lo = least
      else if (!this.viewValue.zero && least > 0 && hi > 0 && (hi - least) / hi < 0.6) lo = least
    }
    if (this.showNotes && this.hasRuleValue && this.ruleValue.at != null && !pinned) {
      hi = Math.max(hi, Number(this.ruleValue.at))
    }
    if (hi <= lo) hi = lo + 1

    const y = (log ? scaleLog() : scaleLinear()).domain([lo, hi]).range([high - pad.b, pad.t])
    if (!log && !pinned && !this.sparkValue) y.nice(4)

    return { x, y, lo: y.domain()[0], line, high, pad, pinned, log, first, last, windowed: !!window }
  }

  xLabelLayout(rows, band) {
    const widest = rows.reduce((mx, r) => Math.max(mx, axisTextWidth(r.label)), 0)
    if (widest + 12 <= band) return { show: this.everyNth(rows.length, 1) }

    const sets = this.daysValue || this.line ? [] : (binLabels(rows) || [])
    const fits = sets.find((names) => names.every((name) => axisTextWidth(name) + 12 <= band))
    if (fits) return { show: this.everyNth(rows.length, 1), names: fits }

    const names = sets[sets.length - 1]
    const maxLabelWidth = names ? Math.max(...names.map(axisTextWidth)) : widest
    return { show: this.everyNth(rows.length, Math.max(1, Math.ceil((maxLabelWidth + 16) / band))), names }
  }

  everyNth(count, every) {
    const show = new Set()
    for (let i = 0; i < count; i += every) show.add(i)
    return show
  }

  draw(chart, wide) {
    const rows = this.rows
    const all = this.series
    const overlaySeries = this.overlaySeries
    const series = overlaySeries.length ? all.filter((s) => !s.over) : all
    const { x, y, lo, line, high, pad, pinned, log, first, last, windowed } = this.scales(rows, series, wide)
    const band = windowed ? x.step() : (wide - PAD.l - PAD.r) / rows.length
    const labels = this.sparkValue ? { show: new Set() } : this.xLabelLayout(rows, band)
    const mid = (i) => x(i) + x.bandwidth() / 2
    const span = y.domain()[1] - y.domain()[0]
    this.fineTicks = !pinned && this.pctValue && span < 5
    const allIntegers = rows.every((r) => series.every((s) => r[s.k] == null || Number.isInteger(Number(r[s.k]))))
    const tickCount = high < 160 ? 3 : 4
    const ticks = pinned ? [0, 50, 100]
      : log ? logTicks(y.domain()[0], y.domain()[1])
        : y.ticks(tickCount).filter((v) => !allIntegers || Number.isInteger(v))
    const right = wide - pad.r
    const floor = y(lo)

    const gridLines = this.showGrid ? `<g class="grid-set" mask="url(#${this.gid}-fade)">${
      ticks.map((v) => {
        const at = y(v).toFixed(1)
        return `<line class="grid" x1="${pad.l}" y1="${at}" x2="${right}" y2="${at}"/>`
      }).join("")}</g>` : ""
    const grid = this.sparkValue ? "" : gridLines + ticks.map((v) =>
      `<text class="ax" x="${pad.l - 8}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${
        this.tick(v)}</text>`).join("")

    const gaps = rows.map((r, i) => r.gap
      ? `<rect class="donut-hole" x="${x(i).toFixed(1)}" y="${pad.t}" width="${
        Math.max(1, x.step()).toFixed(1)}" height="${(floor - pad.t).toFixed(1)}"/>`
      : "").join("")

    const rule = this.showNotes && this.hasRuleValue && this.ruleValue.at != null
      ? `<line class="mark-rule" x1="${pad.l}" y1="${y(this.ruleValue.at).toFixed(1)}" x2="${
        right}" y2="${y(this.ruleValue.at).toFixed(1)}"/>` + (this.ruleValue.label
        ? `<text class="ax rule-note" x="${right}" y="${
          (y(this.ruleValue.at) - 5).toFixed(1)}" text-anchor="end">${
          esc(this.ruleValue.label)}</text>`
        : "")
      : ""

    const splits = (this.hasSplitsValue && this.showNotes ? this.splitsValue : []).map((split) => {
      const after = Number(split.after)
      if (!(after >= 0) || after >= rows.length - 1) return ""

      const at = (x(after) + x.bandwidth() + x(after + 1)) / 2
      return `<line class="split" x1="${at.toFixed(1)}" y1="${pad.t}" x2="${at.toFixed(1)}" y2="${
        floor}"/>` + (split.label
        ? `<text class="ax split-note" x="${(at + 5).toFixed(1)}" y="${pad.t + 9}">${
          esc(split.label)}</text>`
        : "")
    }).join("")

    const flagged = (this.hasPartialValue ? this.partialValue : []).map(Number)
      .filter((i) => i >= 0 && i < rows.length)
    const bandInset = (x.step() - x.bandwidth()) / 2
    const runs = [...new Set(flagged)].sort((a, b) => a - b).reduce((all, i) => {
      const last = all[all.length - 1]
      if (last && i === last[1] + 1) last[1] = i
      else all.push([i, i])
      return all
    }, [])
    const marks = this.sparkValue || !this.showNotes ? "" : runs.map(([from, to]) => {
      const left = Math.max(pad.l, x(from) - bandInset)
      const width = Math.min(right, x(to) + x.bandwidth() + bandInset) - left
      return `<rect class="partial-area" x="${left.toFixed(1)}" y="${pad.t}" width="${
        width.toFixed(1)}" height="${(floor - pad.t).toFixed(1)}" fill="url(#${this.gid}-hatch)"/>`
    }).join("")

    const weekends = !this.daysValue || this.sparkValue || !this.showNotes ? "" : rows.map((r, i) => {
      if (!ISO.test(r.key)) return ""
      const day = new Date(`${r.key}T00:00:00Z`).getUTCDay()
      if (day !== 0 && day !== 6) return ""
      return `<rect class="weekend" x="${(x(i) - bandInset).toFixed(1)}" y="${pad.t}" width="${
        x.step().toFixed(1)}" height="${(floor - pad.t).toFixed(1)}"/>`
    }).join("")

    let lastLabelEnd = -Infinity
    const names = rows.map((r, i) => {
      if (!labels.show.has(i)) return ""

      const at = mid(i)
      if (windowed && (at < pad.l - 1 || at > right + 1)) return ""
      const text = labels.names ? labels.names[i] : r.label

      const labelWidth = axisTextWidth(text)
      const anchor = at - labelWidth / 2 < 2
        ? "start" : at + labelWidth / 2 > wide - 2 ? "end" : "middle"
      const x = anchor === "start" ? 2 : anchor === "end" ? wide - 2 : at
      const left = anchor === "start" ? x : anchor === "end" ? x - labelWidth : x - labelWidth / 2
      if (left < lastLabelEnd + 12) return ""

      lastLabelEnd = left + labelWidth
      return `<text class="ax xtick" data-x="${at.toFixed(1)}" x="${x.toFixed(1)}" y="${
        high - pad.b + 22}" text-anchor="${anchor}">${esc(text)}</text>`
    }).join("")

    const body = line
      ? this.drawLine(rows, series, { x, y, mid, lo, floor, log })
      : this.drawBars(rows, series, { x, y, floor })
    const brushArea = this.brushValue || this.externalPointer
      ? `<rect class="brush-area" x="0" y="${pad.t}" width="0" height="${
        (floor - pad.t).toFixed(1)}" opacity="0"/>`
      : ""

    const overlayValues = rows.slice(first, last + 1).flatMap((r) => overlaySeries.map((s) => r[s.k])).filter((v) => v != null)
    const y2 = overlaySeries.length
      ? scaleLinear().domain([0, Math.max(1, ...overlayValues.map(Number))]).range([floor, pad.t]).nice(3)
      : null
    const overlayMarkup = overlaySeries.length ? this.drawOverlay(rows, overlaySeries, { mid, y2, floor }) : ""
    const rightAxis = y2
      ? y2.ticks(3).filter((v) => Number.isInteger(v)).map((v) =>
        `<text class="ax ax-over" x="${(right + 8).toFixed(1)}" y="${(y2(v) + 3.5).toFixed(1)}">${
          axisLabel(v)}</text>`).join("")
      : ""

    const areaGradient = line && !log && series.length === 1 && (lo === 0 || this.sparkValue)
      ? `<linearGradient id="${this.gid}" x1="0" y1="0" x2="0" y2="1">
          <stop class="top ${this.seriesClass(series[0])}"${this.tint(series[0])} offset="0"/>
          <stop class="bot ${this.seriesClass(series[0])}"${this.tint(series[0])} offset="1"/>
          </linearGradient>`
      : ""
    const edge = `<linearGradient id="${this.gid}-edge" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#fff" stop-opacity="0"/>
        <stop offset="0.06" stop-color="#fff" stop-opacity="1"/>
        <stop offset="0.94" stop-color="#fff" stop-opacity="1"/>
        <stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
      <mask id="${this.gid}-fade" maskUnits="userSpaceOnUse" x="0" y="0" width="${wide}" height="${high}">
        <rect x="${pad.l}" y="0" width="${(right - pad.l).toFixed(1)}" height="${high}"
          fill="url(#${this.gid}-edge)"/></mask>`
    const overlayGradients = overlaySeries.map((s, n) => `<linearGradient id="${this.gid}-o${n}" x1="0" y1="0" x2="0" y2="1">
        <stop class="top ${this.seriesClass(s)}"${this.tint(s)} offset="0"/>
        <stop class="bot ${this.seriesClass(s)}"${this.tint(s)} offset="1"/></linearGradient>`).join("")
    const hatch = `<pattern id="${this.gid}-hatch" width="6" height="6" patternUnits="userSpaceOnUse"
        patternTransform="rotate(45)"><line class="hatch" x1="0" y1="0" x2="0" y2="6"/></pattern>`
    const clipId = `${this.gid}-clip`
    const clipPath = windowed
      ? `<clipPath id="${clipId}"><rect x="${pad.l}" y="0" width="${(right - pad.l).toFixed(1)}" height="${
        (floor + 1).toFixed(1)}"/></clipPath>`
      : ""
    const clipped = (content) => (windowed ? `<g clip-path="url(#${clipId})">${content}</g>` : content)
    const defs = areaGradient + edge + overlayGradients + hatch + clipPath

    const cursor = (this.sparkValue && !line) ? "" :
      `<line class="cur" x1="0" y1="${pad.t}" x2="0" y2="${floor}" opacity="0"/>` +
      (line
        ? series.map((s) => `<circle class="dot ${this.seriesClass(s)}"${this.tint(s)} data-s="${s.k}" r="${
          this.sparkValue ? 3.2 : 4}" fill="currentColor" opacity="0"/>`).join("")
        : "")
    const overlayDots = overlaySeries.map((s) => `<circle class="dot ${this.seriesClass(s)}"${this.tint(s)} data-s="${
      s.k}" data-axis="2" r="4" fill="currentColor" opacity="0"/>`).join("")
    const pinIndex = this.viewValue.pin
    const pinMark = Number.isInteger(pinIndex) && pinIndex >= first && pinIndex <= last
      ? this.pinMark(mid(pinIndex), pad.t, floor)
      : ""

    const pill = this.sparkValue ? "" :
      `<g class="x-pill" opacity="0"><rect y="${(high - pad.b + 6).toFixed(1)}" height="${PILL_H}"
        rx="6" width="0"/><text y="${(high - pad.b + 6 + PILL_H / 2 + 4).toFixed(1)}"
        text-anchor="middle"></text></g>`

    const base = this.sparkValue
      ? ""
      : `<line class="base" mask="url(#${this.gid}-fade)" x1="${pad.l}" y1="${floor}" x2="${
        right}" y2="${floor}"/>`

    const axisTitles = this.sparkValue ? "" : [
      this.xlabelValue
        ? `<text class="ax" x="${((pad.l + right) / 2).toFixed(1)}" y="${high - 9}"
          text-anchor="middle">${esc(this.xlabelValue)}</text>`
        : "",
      this.ylabelValue
        ? `<text class="ax" transform="translate(15 ${((pad.t + floor) / 2).toFixed(1)}) rotate(-90)"
          text-anchor="middle">${esc(this.ylabelValue)}</text>`
        : ""
    ].join("")

    chart.querySelector("svg")?.remove()
    chart.insertAdjacentHTML("afterbegin",
      `<svg width="${wide}" height="${high}" viewBox="0 0 ${wide} ${high}" role="img"
        aria-label="${esc(this.summary(rows, series))}"><defs>${defs}</defs>${clipped(weekends + marks + gaps)}${
        grid}` +
      `${base}${rule}${brushArea}${cursor}${clipped(body + overlayMarkup + splits)}${pinMark}${overlayDots}${names}${rightAxis}${axisTitles}${
        pill}</svg>`)

    if (this.firstDraw) {
      this.firstDraw = false
      chart.classList.add("is-entering")
      clearTimeout(this.enterTimer)
      this.enterTimer = setTimeout(() => chart.classList.remove("is-entering"), 1400)
    }

    this.geom = {
      x, y, y2, mid, lo, line, log, wide, high, rows, series: all, bars: series, floor, pad, first, last,
      tops: rows.map((r) => this.stack
        ? y(this.sum(r, series))
        : Math.min(...series.map((s) => r[s.k] == null || (log && r[s.k] <= 0) ? high : y(r[s.k]))))
    }
    if (this.at != null) this.show(clamp(this.at, first, last), { silent: true })
  }

  drawBars(rows, series, { x, y, floor }) {
    if (this.stack) return this.drawStack(rows, series, { x, y, floor })

    const sub = scaleBand()
      .domain(series.map((s) => s.k))
      .range([0, x.bandwidth()])
      .padding(series.length > 1 ? 0.16 : 0)

    return rows.map((r, i) => {
      const bars = series.map((s) => {
        const v = r[s.k]
        if (v == null) return ""

        let wide = sub.bandwidth()
        let at = x(i) + sub(s.k)
        if (wide > BAR_CAP) {
          at += (wide - BAR_CAP) / 2
          wide = BAR_CAP
        }
        if (Number(v) === 0) {
          return `<rect class="${this.seriesClass(s)}"${this.mark(s)} fill="currentColor" opacity="0.45"
            x="${at.toFixed(1)}" y="${(floor - 2).toFixed(1)}"
            width="${wide.toFixed(1)}" height="2" rx="1"/>`
        }
        const tall = Math.max(floor - y(v), 2)
        return `<path class="bar ${this.seriesClass(s)}"${this.mark(s)} fill="currentColor" d="${
          topBar(at, floor - tall, wide, tall, Math.min(BAR_R, wide / 2))}"/>`
      }).join("")

      return `<g class="mark" data-i="${i}" style="--i:${i}">${bars}</g>`
    }).join("")
  }

  drawStack(rows, series, { x, y, floor }) {
    const caps = this.hasCapsValue ? this.capsValue : []
    const ceiling = this.pad.t + 9

    return rows.map((r, i) => {
      let wide = x.bandwidth()
      let at = x(i)
      if (wide > BAR_CAP) {
        at += (wide - BAR_CAP) / 2
        wide = BAR_CAP
      }

      let below = 0
      const bars = series.map((s, s_i) => {
        const v = r[s.k]
        if (v == null) return ""

        const under = y(below)
        below += Number(v)
        const top = y(below)
        const tall = Math.max(0, under - top - (s_i ? SEG_GAP : 0))
        if (!(tall > 0)) return ""

        const cap = s_i === series.length - 1 ? Math.min(BAR_R, wide / 2) : 0
        return `<path class="bar ${this.seriesClass(s)}"${this.mark(s)} fill="currentColor" d="${
          topBar(at, top, wide, tall, cap)}"/>`
      }).reverse().join("")

      const cap = caps[i]
      const capLabel = cap == null || cap.v == null ? "" :
        `<text class="cap" x="${(at + wide / 2).toFixed(1)}" y="${
          Math.max(ceiling, y(Number(cap.v)) - 7).toFixed(1)}" text-anchor="middle">${
          esc(cap.t)}</text>`

      return `<g class="mark" data-i="${i}" style="--i:${i}">${bars}${capLabel}</g>`
    }).join("")
  }

  drawLine(rows, series, { mid, y, lo, floor, log }) {
    const curve = curveMonotoneX
    const plottable = (v) => v != null && (!log || Number(v) > 0)
    const pts = (s) => rows.map((r, i) => ({ i, v: plottable(r[s.k]) ? r[s.k] : null }))
    const path = lineOf().defined((d) => d.v != null).x((d) => mid(d.i)).y((d) => y(d.v))
      .curve(curve)
    const under = areaOf().defined((d) => d.v != null).x((d) => mid(d.i)).y0(floor)
      .y1((d) => y(d.v)).curve(curve)
    const solid = series.filter((s) => !s.ghost)
    const showAreaFill = !log && solid.length === 1 && (lo === 0 || this.sparkValue)

    return series.map((s) => {
      const points = pts(s)
      const fill = showAreaFill && !s.ghost
        ? `<path class="wash" data-series="${s.k}" fill="url(#${this.gid})" mask="url(#${this.gid}-fade)" d="${
          under(points)}"/>` : ""
      const dash = s.ghost ? ' stroke-dasharray="5 4"' : ' pathLength="1"'
      return `${fill}${this.bridge(points, s, mid, y)}<path class="${s.ghost ? "" : "stroke-line "}${
        this.seriesClass(s)}"${this.mark(s)} fill="none" stroke="currentColor"
        stroke-width="${s.ghost ? 1.5 : 2}"${dash} stroke-linejoin="round" stroke-linecap="round"
        d="${path(points)}"/>${this.isolatedDots(points, s, mid, y)}`
    }).join("")
  }

  drawOverlay(rows, overlaySeries, { mid, y2, floor }) {
    const curve = curveMonotoneX
    return overlaySeries.map((s, n) => {
      const points = rows.map((r, i) => ({ i, v: r[s.k] }))
      const path = lineOf().defined((d) => d.v != null).x((d) => mid(d.i)).y((d) => y2(d.v)).curve(curve)
      const under = areaOf().defined((d) => d.v != null).x((d) => mid(d.i)).y0(floor)
        .y1((d) => y2(d.v)).curve(curve)
      return `<path class="wash wash-over" data-series="${s.k}" fill="url(#${this.gid}-o${n})" mask="url(#${this.gid}-fade)"
          d="${under(points)}"/>` +
        `<path class="stroke-line ${this.seriesClass(s)}"${this.mark(s)} pathLength="1" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"
          d="${path(points)}"/>`
    }).join("")
  }

  pinMark(at, top, floor) {
    const x = at.toFixed(1)
    return `<g class="pin-mark" aria-hidden="true"><line x1="${x}" x2="${x}" y1="${top - 4}" y2="${floor}"/>` +
      `<circle cx="${x}" cy="${top - 4}" r="3"/></g>`
  }

  bridge(points, s, mid, y) {
    const at = points.filter((d) => d.v != null)
    const spans = at.slice(1)
      .map((d, k) => [at[k], d])
      .filter(([a, b]) => b.i - a.i > 1)
      .map(([a, b]) => `M${mid(a.i)},${y(a.v)}L${mid(b.i)},${y(b.v)}`)
    if (!spans.length) return ""

    return `<path class="${this.seriesClass(s)}"${this.mark(s)} fill="none" stroke="currentColor"
      stroke-width="${s.ghost ? 1.5 : 2}" stroke-dasharray="2 3" stroke-linecap="round"
      opacity="0.5" d="${spans.join("")}"/>`
  }

  isolatedDots(points, s, mid, y) {
    return points.filter((d, i) =>
      d.v != null && points[i - 1]?.v == null && points[i + 1]?.v == null
    ).map((d) =>
      `<circle class="${this.seriesClass(s)}"${this.mark(s)} fill="currentColor" stroke="none"
        cx="${mid(d.i)}" cy="${y(d.v)}" r="${s.ghost ? 1.5 : 2}"/>`
    ).join("")
  }

  summary(rows, series) {
    const title = this.viewValue.title ||
      this.element.closest(".card")?.querySelector(".card-title")?.textContent?.trim()
    const seriesNames = series.map((s) => s.n).join(" and ")
    const shape = this.sparkValue ? "trend" : this.stack ? "stacked bar chart"
      : this.line ? "line chart" : "bar chart"
    const values = rows.flatMap((r) => series.map((s) => r[s.k])).filter((v) => v != null)
    const gapCount = rows.filter((r) => r.gap).length
    const range = values.length
      ? `, low ${this.format(Math.min(...values))}, high ${this.format(Math.max(...values))}`
      : ""
    const latest = rows.length && series.length
      ? `, latest ${this.format(rows[rows.length - 1][series[0].k])}`
      : ""
    const unit = this.daysValue ? "day" : "point"
    const missing = gapCount ? `, ${gapCount} ${unit}${gapCount > 1 ? "s" : ""} not measurable` : ""
    return `${title || seriesNames} ${shape}, ${rows.length} points, ${rows[0].label} to ${
      rows[rows.length - 1].label}${range}${latest}${missing}`
  }

  indexAtPointer(event, loose = false) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    const mx = event.clientX - box.left
    const my = event.clientY - box.top
    if (!loose && (mx < g.pad.l || mx > g.wide - g.pad.r || my > g.high - g.pad.b)) return null

    return clamp(Math.floor((mx - g.x.range()[0]) / g.x.step()), g.first, g.last)
  }

  track(event) {
    if (this.brushDrag) return

    const i = this.indexAtPointer(event)
    if (i == null) return this.clear()

    this.show(i)
  }

  press(event) {
    if (event.button !== 0) return

    const i = this.indexAtPointer(event)
    if (i == null) return

    event.preventDefault()
    this.brushDrag = { from: i, to: i }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    this.span()
  }

  drag(event) {
    if (!this.brushDrag) return

    this.brushDrag.to = this.indexAtPointer(event, true)
    this.span()
  }

  release(event) {
    const selection = this.brushDrag
    if (!selection) return

    this.brushDrag = null
    if (event.type === "pointercancel") return this.clear()

    this.navigateToRange(Math.min(selection.from, selection.to), Math.max(selection.from, selection.to))
  }

  span() {
    this.highlightRows(Math.min(this.brushDrag.from, this.brushDrag.to), Math.max(this.brushDrag.from, this.brushDrag.to))
  }

  highlightRows(lo, hi) {
    const g = this.geom
    const chart = this.element.querySelector(".chart")

    chart.querySelector(".tip")?.classList.remove("on")
    chart.querySelector(".cur")?.setAttribute("opacity", "0")
    chart.querySelectorAll(".mark").forEach((mark) =>
      mark.classList.toggle("fade", +mark.dataset.i < lo || +mark.dataset.i > hi))

    const bandInset = (g.x.step() - g.x.bandwidth()) / 2
    const left = Math.max(g.pad.l, g.x(lo) - bandInset)
    const right = Math.min(g.wide - g.pad.r, g.x(hi) + g.x.bandwidth() + bandInset)
    const area = chart.querySelector(".brush-area")
    area?.setAttribute("x", left.toFixed(1))
    area?.setAttribute("width", (right - left).toFixed(1))
    area?.setAttribute("opacity", "1")

    const rangeLabel = lo === hi ? g.rows[lo].label : `${g.rows[lo].label} to ${g.rows[hi].label}`
    this.pill(chart, (left + right) / 2, rangeLabel)
    chart.querySelector(".chart-caption").textContent = rangeLabel
  }

  navigateToRange(lo, hi) {
    const g = this.geom
    if (!g || !this.hasBrushHrefValue) return

    const keys = this.hasBrushKeysValue && this.brushKeysValue.length === g.rows.length
      ? this.brushKeysValue
      : g.rows.map((row) => row.key)
    const url = new URL(this.brushHrefValue, window.location.href)
    url.searchParams.set("start", keys[lo])
    url.searchParams.set("end", keys[hi])
    if (window.Turbo) window.Turbo.visit(url.toString())
    else window.location.assign(url.toString())
  }

  key(event) {
    const g = this.geom
    if (!g) return

    const { first, last } = g
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    let next = this.at

    if (step) next = this.at == null ? (step > 0 ? first : last) : clamp(this.at + step, first, last)
    else if (event.key === "Home") next = first
    else if (event.key === "End") next = last
    else if (event.key === "Escape") return this.clear()
    else if (event.key === "Enter" && this.brushValue && this.at != null) {
      event.preventDefault()
      return this.navigateToRange(this.at, this.at)
    }
    else return

    event.preventDefault()
    this.show(next, { source: "keyboard" })
  }

  show(i, { source = "pointer", silent = false } = {}) {
    const g = this.geom
    const chart = this.element.querySelector(".chart")
    const row = g.rows[i]
    this.at = i
    if (!silent) this.announcePoint(i, source)

    const lines = row.gap
      ? `<div class="row"><i class="donut-hole-dot"></i>${
        esc(row.why || "not fetched")}<b>n/a</b></div>`
      : g.series.map((s) => row[s.k] == null ? "" :
        `<div class="row"><i class="${this.seriesClass(s)}"${this.tint(s)}></i>${esc(s.n)}<b><span>${
          this.format(row[s.k])}</span>${row[s.c] == null ? "" : `<u>${F(row[s.c])}</u>`}</b></div>`)
        .join("")

    const totalRow = this.stack && !row.gap && !this.pctValue
      ? `<div class="row row-sum"><i></i>total<b><span>${
        this.format(this.sum(row, g.bars))}</span></b></div>`
      : ""

    const partialRow = this.hasPartialValue && this.partialValue.map(Number).includes(i)
      ? `<div class="row row-note"><i class="donut-hole-dot"></i>${
        esc(this.partialNoteValue || "period not complete")}</div>`
      : ""

    const text = row.tip
      ? `<div class="row row-note"><i></i>${esc(row.tip)}</div>`
      : ""

    const note = this.hasRuleValue && this.ruleValue.note
      ? `<div class="row row-note"><i></i>${esc(this.ruleValue.note)}</div>`
      : ""

    const tip = chart.querySelector(".tip")
    tip.innerHTML = `<div class="t">${esc(row.label)}</div>${lines}${totalRow}${text}${partialRow}${note}`
    tip.classList.add("on")

    const at = g.mid(i)
    const tipWide = tip.offsetWidth || 190
    const bandL = g.line ? at : g.x(i)
    const bandR = g.line ? at : g.x(i) + g.x.bandwidth()

    let left = bandR + 12
    if (left + tipWide > g.wide) left = bandL - 12 - tipWide
    if (left < 0) left = clamp(at - tipWide / 2, 0, Math.max(0, g.wide - tipWide))

    tip.style.left = `${left}px`
    tip.style.top = `${g.pad.t}px`

    chart.querySelectorAll(".mark").forEach((mark) =>
      mark.classList.toggle("fade", +mark.dataset.i !== i))
    this.pill(chart, at, row.label)

    const cur = chart.querySelector(".cur")
    if (cur) {
      cur.setAttribute("x1", at)
      cur.setAttribute("x2", at)
      cur.setAttribute("opacity", "1")
      chart.querySelectorAll(".dot").forEach((dot) => {
        const v = row[dot.dataset.s]
        if (v == null || (g.log && v <= 0)) return dot.setAttribute("opacity", "0")

        dot.setAttribute("cx", at)
        dot.setAttribute("cy", dot.dataset.axis === "2" && g.y2 ? g.y2(v) : g.y(v))
        dot.setAttribute("opacity", "1")
      })
    }

    chart.querySelector(".chart-caption").textContent = row.gap
      ? `${row.label}, ${row.why || "not fetched"}`
      : `${row.label}, ${g.series.map((s) => `${s.n} ${this.format(row[s.k])}`).join(", ")}${
        this.stack ? `, total ${this.format(this.sum(row, g.bars))}` : ""}`
  }

  pill(chart, at, label) {
    const g = this.geom
    const pill = chart.querySelector(".x-pill")
    if (!pill || !g) return

    const text = String(label)
    const wide = axisTextWidth(text) + 20
    const left = clamp(at - wide / 2, g.pad.l - 4, g.wide - g.pad.r - wide + 4)
    const box = pill.querySelector("rect")
    box.setAttribute("x", left.toFixed(1))
    box.setAttribute("width", wide.toFixed(1))
    const pillText = pill.querySelector("text")
    pillText.setAttribute("x", (left + wide / 2).toFixed(1))
    pillText.textContent = text
    pill.setAttribute("opacity", "1")

    chart.querySelectorAll(".xtick").forEach((tick) => {
      const overlapsPill = Math.abs(Number(tick.dataset.x) - at) < wide / 2 + 18
      if (overlapsPill) tick.setAttribute("opacity", "0")
      else tick.removeAttribute("opacity")
    })
  }

  clear() {
    const chart = this.element.querySelector(".chart")
    if (!chart) return

    this.at = null
    this.announcePoint(null, "pointer")
    chart.querySelector(".tip")?.classList.remove("on")
    chart.querySelector(".cur")?.setAttribute("opacity", "0")
    chart.querySelectorAll(".dot").forEach((dot) => dot.setAttribute("opacity", "0"))
    chart.querySelectorAll(".mark").forEach((mark) => mark.classList.remove("fade"))
    chart.querySelector(".x-pill")?.setAttribute("opacity", "0")
    chart.querySelector(".brush-area")?.setAttribute("opacity", "0")
    chart.querySelectorAll(".xtick").forEach((tick) => tick.removeAttribute("opacity"))
    const caption = chart.querySelector(".chart-caption")
    if (caption) caption.textContent = ""
  }
}
