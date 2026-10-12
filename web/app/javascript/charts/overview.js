import { line as lineOf, curveMonotoneX } from "d3-shape"
import { clampWindow, shiftWindow, windowAround, minimumSpan } from "charts/frame"

const HANDLE_HIT = 7
const CLICK_TOLERANCE = 3
const INSET = 4
const COLUMN_FILL = 0.7

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

export class Overview {
  constructor(element, { onWindow, onReset }) {
    this.element = element
    this.onWindow = onWindow
    this.onReset = onReset
    this.geometry = null
    this.drag = null
    this.onPointerdown = this.onPointerdown.bind(this)
    this.onPointermove = this.onPointermove.bind(this)
    this.onPointerup = this.onPointerup.bind(this)
    this.onPointercancel = this.onPointercancel.bind(this)
    this.onDoubleClick = this.onDoubleClick.bind(this)
    element.addEventListener("pointerdown", this.onPointerdown)
    element.addEventListener("pointermove", this.onPointermove)
    element.addEventListener("pointerup", this.onPointerup)
    element.addEventListener("pointercancel", this.onPointercancel)
    element.addEventListener("dblclick", this.onDoubleClick)
  }

  destroy() {
    this.element.removeEventListener("pointerdown", this.onPointerdown)
    this.element.removeEventListener("pointermove", this.onPointermove)
    this.element.removeEventListener("pointerup", this.onPointerup)
    this.element.removeEventListener("pointercancel", this.onPointercancel)
    this.element.removeEventListener("dblclick", this.onDoubleClick)
    this.clear()
  }

  clear() {
    this.geometry = null
    this.drag = null
    this.element.replaceChildren()
  }

  render({ count, window, bounds, series }) {
    const width = this.element.clientWidth
    const height = this.element.clientHeight
    if (!width || !height || !count) return

    const box = this.element.getBoundingClientRect()
    const left = Math.max(0, bounds.left - box.left)
    const right = Math.min(width, bounds.right - box.left)
    const span = Math.max(1, right - left)
    const toX = (unit) => left + (unit / count) * span
    const top = INSET
    const bottom = height - INSET
    const [start, end] = window || [0, count]
    const x0 = toX(start)
    const x1 = toX(end)

    const marks = series.kind === "bars"
      ? this.columns(series.values, { toX, span, count, top, bottom })
      : this.lines(series.lines, { toX, top, bottom })

    this.element.innerHTML = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">` +
      `<rect class="overview-track" x="${left.toFixed(1)}" y="0" width="${span.toFixed(1)}" height="${height}" rx="6"/>${marks}` +
      `<rect class="overview-mask" x="${left.toFixed(1)}" y="0" width="${Math.max(0, x0 - left).toFixed(1)}" height="${height}"/>` +
      `<rect class="overview-mask" x="${x1.toFixed(1)}" y="0" width="${Math.max(0, right - x1).toFixed(1)}" height="${height}"/>` +
      `<rect class="overview-window" x="${x0.toFixed(1)}" y="0.5" width="${Math.max(1, x1 - x0).toFixed(1)}" height="${
        height - 1}" rx="5"/>` +
      this.handle(x0, height) + this.handle(x1, height) + "</svg>"
    this.geometry = { count, left, span, x0, x1, window: [start, end] }
  }

  columns(values, { toX, span, count, top, bottom }) {
    const peak = Math.max(1, ...values)
    const width = Math.max(0.6, (span / count) * COLUMN_FILL)
    const offset = (span / count - width) / 2
    return values.map((value, i) => {
      if (!(value > 0)) return ""
      const tall = (value / peak) * (bottom - top)
      return `<rect class="overview-column" x="${(toX(i) + offset).toFixed(2)}" y="${(bottom - tall).toFixed(1)}" width="${
        width.toFixed(2)}" height="${tall.toFixed(1)}"/>`
    }).join("")
  }

  lines(lines, { toX, top, bottom }) {
    const all = lines.flatMap((line) => line.values).filter((value) => value != null)
    if (!all.length) return ""

    const low = Math.min(...all)
    const high = Math.max(...all)
    const toY = (value) => bottom - ((value - low) / (high - low || 1)) * (bottom - top)
    const path = lineOf().defined((point) => point.value != null)
      .x((point) => toX(point.index + 0.5)).y((point) => toY(point.value)).curve(curveMonotoneX)
    return lines.map((line) => {
      const style = line.color ? ` style="color:${esc(line.color)}"` : ""
      const points = line.values.map((value, index) => ({ index, value }))
      return `<path class="overview-line ${line.colorClass}"${style} d="${path(points) || ""}"/>`
    }).join("")
  }

  handle(x, height) {
    return `<rect class="overview-handle" x="${(x - 3).toFixed(1)}" y="${(height / 2 - 8).toFixed(1)}" width="6" height="16" rx="2"/>`
  }

  unitAt(clientX) {
    const g = this.geometry
    const x = clientX - this.element.getBoundingClientRect().left
    return Math.min(g.count, Math.max(0, ((x - g.left) / g.span) * g.count))
  }

  modeAt(clientX) {
    const g = this.geometry
    const x = clientX - this.element.getBoundingClientRect().left
    if (Math.abs(x - g.x0) <= HANDLE_HIT) return "start"
    if (Math.abs(x - g.x1) <= HANDLE_HIT) return "end"
    if (x > g.x0 && x < g.x1) return "move"
    return "new"
  }

  onPointerdown(event) {
    if (!this.geometry || event.button !== 0) return

    event.preventDefault()
    this.capturePointer(event.pointerId)
    this.drag = {
      mode: this.modeAt(event.clientX), originX: event.clientX,
      originUnit: this.unitAt(event.clientX), window: this.geometry.window, hasMoved: false
    }
  }

  onPointermove(event) {
    if (!this.geometry) return

    const drag = this.drag
    if (!drag) {
      this.element.style.cursor = { start: "ew-resize", end: "ew-resize", move: "grab", new: "pointer" }[this.modeAt(event.clientX)]
      return
    }
    if (Math.abs(event.clientX - drag.originX) > CLICK_TOLERANCE) drag.hasMoved = true
    if (!drag.hasMoved) return

    const unit = this.unitAt(event.clientX)
    const count = this.geometry.count
    const minSpan = minimumSpan(count)
    const [start, end] = drag.window
    let window
    if (drag.mode === "start") window = [Math.min(Math.max(unit, 0), end - minSpan), end]
    else if (drag.mode === "end") window = [start, Math.max(Math.min(unit, count), start + minSpan)]
    else if (drag.mode === "move") window = shiftWindow(drag.window, count, unit - drag.originUnit)
    else window = windowAround(Math.min(drag.originUnit, unit), Math.max(drag.originUnit, unit), count)
    if (drag.mode === "move") this.element.style.cursor = "grabbing"
    this.onWindow(clampWindow(window, count), { animate: false })
  }

  onPointerup(event) {
    const drag = this.drag
    this.drag = null
    this.element.style.cursor = ""
    if (!drag || !this.geometry || drag.hasMoved || drag.mode !== "new") return

    const [start, end] = drag.window
    const unit = this.unitAt(event.clientX)
    this.onWindow(shiftWindow(drag.window, this.geometry.count, unit - (start + end) / 2), { animate: true })
  }

  capturePointer(pointerId) {
    try {
      this.element.setPointerCapture(pointerId)
    } catch {
      return false
    }
    return true
  }

  onPointercancel() {
    this.drag = null
  }

  onDoubleClick() {
    this.onReset()
  }
}
