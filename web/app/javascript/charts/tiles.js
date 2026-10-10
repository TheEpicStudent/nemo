import { Controller } from "@hotwired/stimulus"
import { squarify } from "charts/squarify"

const GAP = 3
const RADIUS = 6
const PIN_INSET = 1
const TIP_OFFSET = 10
const SANS = '"Geist", ui-sans-serif, system-ui, sans-serif'
const RULER = typeof document === "undefined"
  ? null
  : document.createElement("canvas").getContext("2d")

export const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

export const N = (v) => v == null ? "n/a" : Number(v).toLocaleString("en-US")

export const PC = (v, d = 1) => v == null ? "n/a" : `${Number(v).toFixed(d)}%`

export function fit(text, size, weight = 600) {
  if (!RULER) return text.length * size * 0.6

  RULER.font = `${weight} ${size}px ${SANS}`
  return RULER.measureText(text).width
}

export function clip(text, size, room, weight) {
  if (room <= 0) return null
  if (fit(text, size, weight) <= room) return text

  for (let n = text.length - 1; n >= 2; n--) {
    const cut = `${text.slice(0, n)}…`
    if (fit(cut, size, weight) <= room) return cut
  }
  return null
}

const withoutPin = ({ pin: _pin, ...rest }) => JSON.stringify(rest)

export class TileChart extends Controller {
  static values = { tiles: Array, height: Number, view: Object }

  connect() {
    this.at = null
    this.wide = 0
    this.fillHeight = 0
    const name = this.identifier
    const hover = this.externalPointer ? "" : `mousemove->${name}#track mouseleave->${name}#clear `
    this.element.innerHTML = `<div class="${this.boxClass} tipped" tabindex="0"
      data-action="${hover}keydown->${name}#key"
      ><div class="tip"></div><span class="chart-caption" aria-live="polite"></span></div>`
    this.box = this.element.querySelector(".tree")
    this.watcher = new ResizeObserver(() => this.measure())
    this.watcher.observe(this.box)
    this.measure()
    this.ready = true
    if (this.hasViewValue) this.dispatch("ready", { prefix: "chart" })
  }

  disconnect() {
    this.ready = false
    this.watcher?.disconnect()
  }

  viewValueChanged(value, previous) {
    if (!this.ready) return

    this.redraw()
    if (!previous || withoutPin(value) !== withoutPin(previous)) this.dispatch("update", { prefix: "chart" })
  }

  get boxClass() {
    return "tree"
  }

  get defaultHeight() {
    return 400
  }

  get fill() {
    return !!this.viewValue.fill
  }

  get externalPointer() {
    return this.viewValue.pointer === "external"
  }

  get hiddenKeys() {
    return new Set(this.viewValue.hidden || [])
  }

  get showLabels() {
    return this.viewValue.labels !== false
  }

  get pinned() {
    return Number.isInteger(this.viewValue.pin) ? this.viewValue.pin : null
  }

  get high() {
    if (this.fill && this.fillHeight > 0) return this.fillHeight
    return this.hasHeightValue && this.heightValue > 0 ? this.heightValue : this.defaultHeight
  }

  measure() {
    const wide = this.box ? this.box.clientWidth : 0
    const height = this.fill && this.box ? this.box.clientHeight : 0
    if (!wide || (wide === this.wide && height === this.fillHeight)) return

    this.wide = wide
    this.fillHeight = height
    this.draw()
  }

  redraw() {
    if (this.wide) this.draw()
  }

  draw() {
    const items = this.items()
    const wide = this.wide
    const high = this.high
    this.geom = { wide, high }
    this.zones = []
    this.box.querySelector("svg")?.remove()
    if (!items.length) {
      this.clear()
      return
    }

    let cells = ""
    let ring = ""
    squarify(items, 0, 0, wide, high, []).forEach((item) => {
      const w = Math.max(0, item.w - GAP)
      const h = Math.max(0, item.h - GAP)
      if (!(w > 1 && h > 1)) return

      const tile = { ...item, x: item.x + GAP / 2, y: item.y + GAP / 2, w, h, rx: Math.min(RADIUS, w / 4, h / 4) }
      const tone = this.toneOf(item)
      cells += `<g class="cell" data-i="${item.i}" data-series="${this.seriesOf(item)}"><rect class="${tone}"
        x="${tile.x.toFixed(1)}" y="${tile.y.toFixed(1)}"
        width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${tile.rx.toFixed(1)}"/>${
        this.showLabels ? this.labelMarkup(tile) : ""}</g>`
      if (item.i === this.pinned) ring = this.pinMarkup(tile)

      this.zones.push({ i: item.i, row: item.row, tone, cx: item.x + item.w / 2, cy: item.y + item.h / 2,
        x0: item.x, y0: item.y, x1: item.x + item.w, y1: item.y + item.h })
    })

    this.box.insertAdjacentHTML("afterbegin",
      `<svg width="${wide}" height="${high}" viewBox="0 0 ${wide} ${high}" role="img"
        aria-label="${esc(this.summary())}">${cells}${ring}</svg>`)

    if (this.at == null) return
    if (this.zoneFor(this.at)) this.show(this.at, { silent: true })
    else this.clear()
  }

  pinMarkup(tile) {
    return `<rect class="pin-ring" x="${(tile.x - PIN_INSET).toFixed(1)}" y="${(tile.y - PIN_INSET).toFixed(1)}"
      width="${(tile.w + PIN_INSET * 2).toFixed(1)}" height="${(tile.h + PIN_INSET * 2).toFixed(1)}"
      rx="${(tile.rx + PIN_INSET).toFixed(1)}"/>`
  }

  pointKey(index) {
    const row = this.tilesValue[index]
    return row ? String(row.name ?? row.label) : null
  }

  indexOfKey(key) {
    return this.tilesValue.findIndex((row) => String(row.name ?? row.label) === key)
  }

  zoneFor(i) {
    return this.zones?.find((zone) => zone.i === i) || null
  }

  displayDefaults() {
    return { labels: true }
  }

  displayOptions() {
    return { labels: true }
  }

  spot(event) {
    const svg = this.box?.querySelector("svg")
    if (!svg || !this.zones?.length) return null

    const rect = svg.getBoundingClientRect()
    const mx = (event.clientX - rect.left) / rect.width * this.geom.wide
    const my = (event.clientY - rect.top) / rect.height * this.geom.high
    const hit = this.zones.find((zone) => mx >= zone.x0 && mx <= zone.x1 && my >= zone.y0 && my <= zone.y1)
    return hit ? hit.i : null
  }

  track(event) {
    const i = this.spot(event)
    if (i == null) return this.clear()

    this.show(i)
  }

  key(event) {
    if (!this.zones?.length) return

    const last = this.zones.length - 1
    const position = this.zones.findIndex((zone) => zone.i === this.at)
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    let next
    if (step) next = position < 0 ? (step > 0 ? 0 : last) : Math.min(last, Math.max(0, position + step))
    else if (event.key === "Home") next = 0
    else if (event.key === "End") next = last
    else if (event.key === "Escape") return this.clear()
    else return

    event.preventDefault()
    this.show(this.zones[next].i, { source: "keyboard" })
  }

  showIndex(index) {
    if (!this.zoneFor(index)) {
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
    const zone = this.zoneFor(i)
    if (!zone) return

    this.at = i
    if (!silent) this.announcePoint(i, source)

    const tip = this.box.querySelector(".tip")
    tip.innerHTML = this.tipMarkup(zone)
    tip.classList.add("on")

    const tipWide = tip.offsetWidth || 190
    const tipHigh = tip.offsetHeight || 90
    const scale = this.box.clientWidth / this.geom.wide
    let left = zone.x1 * scale + TIP_OFFSET
    if (left + tipWide > this.box.clientWidth) left = zone.x0 * scale - TIP_OFFSET - tipWide
    if (left < 0) left = Math.max(0, Math.min(zone.cx * scale - tipWide / 2, this.box.clientWidth - tipWide))
    const top = Math.max(0, Math.min(zone.cy * scale - tipHigh / 2, this.box.clientHeight - tipHigh))
    tip.style.left = `${left}px`
    tip.style.top = `${top}px`

    this.box.classList.add("lit")
    this.box.querySelectorAll(".cell").forEach((cell) => cell.classList.toggle("on", Number(cell.dataset.i) === i))
    this.box.querySelector(".chart-caption").textContent = this.captionFor(zone)
  }

  clear() {
    if (!this.box) return

    this.at = null
    this.announcePoint(null, "pointer")
    this.box.querySelector(".tip")?.classList.remove("on")
    this.box.classList.remove("lit")
    this.box.querySelectorAll(".cell.on").forEach((cell) => cell.classList.remove("on"))
    const say = this.box.querySelector(".chart-caption")
    if (say) say.textContent = ""
  }
}
