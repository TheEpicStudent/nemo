import { Controller } from "@hotwired/stimulus"
import { scaleLinear } from "d3-scale"
import { line as lineOf, area as areaOf, curveLinear } from "d3-shape"

const PAD = { l: 42, r: 14, t: 20, b: 38 }
const TICKS = [0, 25, 50, 75, 100]

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

const pct = (v, d = 1) => `${Number(v).toFixed(d)}%`

const share = (v) => `${+Number(v).toFixed(1)}%`

const withoutPin = ({ pin: _pin, ...rest }) => JSON.stringify(rest)

let seq = 0

export default class extends Controller {
  static values = { points: Array, height: Number, gini: Number, marks: Array, view: Object }

  connect() {
    this.gid = `lz${++seq}`
    this.at = null
    const hover = this.externalPointer ? "" : "mousemove->lorenz#track mouseleave->lorenz#clear "
    this.element.innerHTML = `<div class="chart tipped" tabindex="0"
      data-action="${hover}keydown->lorenz#key"
      ><div class="tip"></div><span class="chart-caption" aria-live="polite"></span></div>`
    const chart = this.element.querySelector(".chart")
    this.watcher = new ResizeObserver(() => this.measure())
    this.watcher.observe(chart)
    this.resized = () => this.measure()
    window.addEventListener("resize", this.resized)
    this.wide = 0
    this.measure()
    this.ready = true
    if (this.hasViewValue) this.dispatch("ready", { prefix: "chart" })
  }

  disconnect() {
    this.ready = false
    this.watcher?.disconnect()
    window.removeEventListener("resize", this.resized)
  }

  viewValueChanged(value, previous) {
    if (!this.ready) return

    this.redraw()
    if (!previous || withoutPin(value) !== withoutPin(previous)) this.dispatch("update", { prefix: "chart" })
  }

  get externalPointer() {
    return this.viewValue.pointer === "external"
  }

  get showGrid() {
    return this.viewValue.grid !== false
  }

  get showNotes() {
    return this.viewValue.notes !== false
  }

  get pinned() {
    return Number.isInteger(this.viewValue.pin) ? this.viewValue.pin : null
  }

  get points() {
    const pts = this.pointsValue
    return !pts.length || pts[0][0] === 0 ? pts : [[0, 0], ...pts]
  }

  get marks() {
    return this.hasMarksValue ? this.marksValue : []
  }

  get high() {
    const chart = this.element.querySelector(".chart")
    const room = chart ? Math.round(chart.clientHeight) : 0
    if (room > 160) return room

    return this.hasHeightValue && this.heightValue > 0 ? this.heightValue : 226
  }

  measure() {
    const chart = this.element.querySelector(".chart")
    const wide = chart ? chart.clientWidth : 0
    const high = this.high
    if (!wide || (wide === this.wide && high === this.tall)) return

    this.wide = wide
    this.tall = high
    this.draw(chart, wide, high)
  }

  redraw() {
    const chart = this.element.querySelector(".chart")
    if (chart && this.wide) this.draw(chart, this.wide, this.tall)
  }

  draw(chart, wide, high) {
    if (!this.pointsValue.length) return

    const x = scaleLinear().domain([0, 100]).range([PAD.l, wide - PAD.r])
    const y = scaleLinear().domain([0, 100]).range([high - PAD.b, PAD.t])

    const seen = this.points
    const path = lineOf().x((d) => x(d[0])).y((d) => y(d[1])).curve(curveLinear)
    const under = areaOf().x((d) => x(d[0])).y0(y(0)).y1((d) => y(d[1])).curve(curveLinear)

    const grid = TICKS.map((v) =>
      (this.showGrid
        ? `<line class="grid" x1="${PAD.l}" y1="${y(v).toFixed(1)}" x2="${
          wide - PAD.r}" y2="${y(v).toFixed(1)}"/>`
        : "") +
      `<text class="ax" x="${PAD.l - 7}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${
        v}%</text>` +
      `<text class="ax" x="${x(v).toFixed(1)}" y="${y(0) + 21}" text-anchor="middle">${
        v}%</text>`).join("")

    const fair = `<line class="fair" x1="${x(0)}" y1="${y(0)}" x2="${x(100)}" y2="${y(100)}"/>`

    const marks = (this.showNotes ? this.marks : []).map(([px, py]) =>
      `<circle class="pin" cx="${x(px).toFixed(1)}" cy="${y(py).toFixed(1)}" r="4"/>`).join("")

    const pinned = this.pinned != null ? seen[this.pinned] : null
    const pin = pinned
      ? `<g class="pin-mark" aria-hidden="true"><line x1="${x(pinned[0]).toFixed(1)}" x2="${
        x(pinned[0]).toFixed(1)}" y1="${PAD.t}" y2="${y(0)}"/><circle cx="${x(pinned[0]).toFixed(1)}" cy="${
        y(pinned[1]).toFixed(1)}" r="4"/></g>`
      : ""

    chart.querySelector("svg")?.remove()
    chart.insertAdjacentHTML("afterbegin",
      `<svg width="${wide}" height="${high}" viewBox="0 0 ${wide} ${high}" role="img"
        aria-label="${esc(this.summary())}"><defs><linearGradient id="${this.gid}" x1="0" y1="0"
          x2="0" y2="1"><stop class="top ser-1" offset="0"/><stop class="bot ser-1" offset="1"/>
          </linearGradient></defs>${grid}${fair}` +
      `<path class="wash-fill" fill="url(#${this.gid})" d="${under(seen)}"/>` +
      `<path class="curve" d="${path(seen)}" fill="none"/>${marks}${pin}` +
      `<line class="base" x1="${PAD.l}" y1="${y(0)}" x2="${wide - PAD.r}" y2="${y(0)}"/>` +
      `<line class="cur" x1="0" y1="${PAD.t}" x2="0" y2="${y(0)}" opacity="0"/>` +
      `<circle class="dot" r="4" opacity="0"/></svg>`)

    this.geom = { x, y, wide, high, pts: seen }
    if (this.at != null) this.show(this.at, { silent: true })
  }

  summary() {
    const pts = this.pointsValue
    const half = pts.find((p) => p[0] === 50)
    const top = pts.find((p) => p[0] === 90)
    const bits = [`concentration curve, ${pts.length} points`]
    if (half) bits.push(`bottom half of posters hold ${pct(half[1])} of messages`)
    if (top) bits.push(`top tenth hold ${pct(100 - top[1])}`)
    if (this.hasGiniValue) bits.push(`Gini ${Number(this.giniValue).toFixed(3)}`)
    return bits.join(", ")
  }

  spot(event) {
    const g = this.geom
    if (!g) return null

    const box = this.element.querySelector(".chart").getBoundingClientRect()
    const mx = event.clientX - box.left
    if (mx < PAD.l || mx > g.wide - PAD.r) return null

    const want = g.x.invert(mx)
    let best = 0
    g.pts.forEach((p, i) => {
      if (Math.abs(p[0] - want) < Math.abs(g.pts[best][0] - want)) best = i
    })
    return best
  }

  track(event) {
    const i = this.spot(event)
    if (i == null) return this.clear()

    this.show(i)
  }

  key(event) {
    const g = this.geom
    if (!g) return

    const last = g.pts.length - 1
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    let next = this.at

    if (step) next = this.at == null ? (step > 0 ? 0 : last) : Math.min(last, Math.max(0, this.at + step))
    else if (event.key === "Home") next = 0
    else if (event.key === "End") next = last
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
    const chart = this.element.querySelector(".chart")
    if (!g || !g.pts[i]) return

    const [px, py] = g.pts[i]
    this.at = i
    if (!silent) this.announcePoint(i, source)

    const tip = chart.querySelector(".tip")
    tip.innerHTML = `<div class="t">bottom ${px}% of posters</div>` +
      `<div class="row"><i class="ser-1"></i>of messages<b>${pct(py, 2)}</b></div>` +
      `<div class="row"><i class="ser-0"></i>if equal<b>${pct(px, 0)}</b></div>`
    tip.classList.add("on")

    const tipWide = tip.offsetWidth || 180
    let left = g.x(px) + 14
    if (left + tipWide > g.wide) left = g.x(px) - 14 - tipWide
    tip.style.left = `${Math.max(0, left)}px`
    tip.style.top = `${PAD.t}px`

    const cur = chart.querySelector(".cur")
    cur.setAttribute("x1", g.x(px))
    cur.setAttribute("x2", g.x(px))
    cur.setAttribute("opacity", "0.6")
    const dot = chart.querySelector(".dot")
    dot.setAttribute("cx", g.x(px))
    dot.setAttribute("cy", g.y(py))
    dot.setAttribute("opacity", "1")

    chart.querySelector(".chart-caption").textContent =
      `bottom ${px} percent of posters hold ${pct(py, 2)} of messages`
  }

  clear() {
    const chart = this.element.querySelector(".chart")
    if (!chart) return

    this.at = null
    this.announcePoint(null, "pointer")
    chart.querySelector(".tip")?.classList.remove("on")
    chart.querySelector(".cur")?.setAttribute("opacity", "0")
    chart.querySelector(".dot")?.setAttribute("opacity", "0")
    const say = chart.querySelector(".chart-caption")
    if (say) say.textContent = ""
  }

  holdingAt(posters) {
    const point = this.points.find((p) => p[0] === posters)
    return point ? point[1] : null
  }

  displayDefaults() {
    return { grid: true, notes: true }
  }

  displayOptions() {
    return { grid: true, notes: this.marks.length > 0 }
  }

  inspectorLabels() {
    return { point: "Point", stats: "Curve" }
  }

  pointDetails(i) {
    const point = this.points[i]
    if (!point) return null

    const [px, py] = point
    const row = (label, text, extra = {}) => ({
      label, colorClass: "", color: null, shape: "none", value: text, change: null, share: null, ...extra
    })
    return {
      title: `Bottom ${share(px)} of posters`,
      qualifier: null,
      tags: [],
      note: null,
      total: null,
      values: [
        row("of messages", pct(py, 2), { colorClass: "ser-1", shape: "line" }),
        row("if equal", share(px), { colorClass: "ser-0", shape: "dashed" }),
        px < 100 && row(`top ${share(100 - px)} hold`, pct(100 - py, 2))
      ].filter(Boolean)
    }
  }

  rangeStats() {
    const top = (posters) => {
      const held = this.holdingAt(100 - posters)
      return held == null ? null : { label: `top ${posters}% hold`, value: pct(100 - held) }
    }
    const half = this.holdingAt(50)
    return {
      summary: [
        this.hasGiniValue && { label: "Gini", value: Number(this.giniValue).toFixed(3) },
        half != null && { label: "bottom half hold", value: pct(half) },
        top(10),
        top(1)
      ].filter(Boolean)
    }
  }

  tableData() {
    return {
      columns: [
        { key: "posters", label: "posters", numeric: true },
        { key: "messages", label: "messages", numeric: true },
        { key: "gap", label: "gap from equal", numeric: true }
      ],
      rows: this.points.map(([px, py], index) => ({
        index,
        values: { posters: Number(px), messages: Number(py), gap: Number((px - py).toFixed(2)) },
        display: { posters: `bottom ${share(px)}`, messages: pct(py, 2), gap: `${(px - py).toFixed(1)} pts` },
        note: null
      })),
      footer: null
    }
  }
}
