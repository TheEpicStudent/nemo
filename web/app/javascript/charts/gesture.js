const DRAG_THRESHOLD = 4
const PAN_THRESHOLD = 2
const WHEEL_ZOOM_RATE = 0.0025
const WHEEL_LINE_ZOOM_RATE = 0.05
const WHEEL_LINE_HEIGHT = 16

export class PlotGestures {
  constructor(element, handlers) {
    this.element = element
    this.handlers = handlers
    this.pointers = new Map()
    this.state = null
    this.onPointerdown = this.onPointerdown.bind(this)
    this.onPointermove = this.onPointermove.bind(this)
    this.onPointerup = this.onPointerup.bind(this)
    this.onPointercancel = this.onPointercancel.bind(this)
    this.onPointerleave = this.onPointerleave.bind(this)
    this.onWheel = this.onWheel.bind(this)
    this.onDoubleClick = this.onDoubleClick.bind(this)
    element.addEventListener("pointerdown", this.onPointerdown)
    element.addEventListener("pointermove", this.onPointermove)
    element.addEventListener("pointerup", this.onPointerup)
    element.addEventListener("pointercancel", this.onPointercancel)
    element.addEventListener("pointerleave", this.onPointerleave)
    element.addEventListener("wheel", this.onWheel, { passive: false })
    element.addEventListener("dblclick", this.onDoubleClick)
  }

  destroy() {
    this.cancel()
    this.element.removeEventListener("pointerdown", this.onPointerdown)
    this.element.removeEventListener("pointermove", this.onPointermove)
    this.element.removeEventListener("pointerup", this.onPointerup)
    this.element.removeEventListener("pointercancel", this.onPointercancel)
    this.element.removeEventListener("pointerleave", this.onPointerleave)
    this.element.removeEventListener("wheel", this.onWheel)
    this.element.removeEventListener("dblclick", this.onDoubleClick)
  }

  get active() {
    return this.state !== null
  }

  cancel() {
    const state = this.state
    this.state = null
    this.pointers.clear()
    if (state) this.handlers.cancel?.(state.mode)
  }

  onPointerdown(event) {
    if (event.button !== 0) return

    this.pointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY })
    this.capturePointer(event.pointerId)

    if (this.pointers.size === 2) {
      this.startPinch()
      return
    }
    if (this.pointers.size > 2) return

    const pan = !!this.handlers.panMode?.()
    this.state = {
      mode: pan ? "pan-press" : "press",
      start: { clientX: event.clientX, clientY: event.clientY },
      last: { clientX: event.clientX, clientY: event.clientY }
    }
  }

  onPointermove(event) {
    if (this.pointers.has(event.pointerId)) {
      this.pointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY })
    }

    const state = this.state
    if (!state) {
      if (event.pointerType !== "touch") this.handlers.hover?.(event)
      return
    }
    if (state.mode === "pinch") {
      this.movePinch()
      return
    }

    const distance = Math.hypot(event.clientX - state.start.clientX, event.clientY - state.start.clientY)
    if (state.mode === "press" && distance > DRAG_THRESHOLD && this.handlers.brushStart?.(state.start) !== false) {
      state.mode = "brush"
    }
    if (state.mode === "pan-press" && distance > PAN_THRESHOLD) state.mode = "pan"

    if (state.mode === "brush") {
      this.handlers.brushMove?.(state.start, event)
    } else if (state.mode === "pan") {
      this.handlers.pan?.(event.clientX - state.last.clientX, event.clientY - state.last.clientY)
    }
    state.last = { clientX: event.clientX, clientY: event.clientY }
  }

  onPointerup(event) {
    this.pointers.delete(event.pointerId)
    const state = this.state
    if (!state) return

    if (state.mode === "pinch") {
      if (this.pointers.size === 0) this.finish(() => this.handlers.pinchEnd?.())
      return
    }

    this.finish(() => {
      if (state.mode === "brush") this.handlers.brushEnd?.(state.start, event)
      else if (state.mode === "pan") this.handlers.panEnd?.()
      else this.handlers.tap?.(event)
    })
  }

  onPointercancel(event) {
    this.pointers.delete(event.pointerId)
    if (this.pointers.size === 0) this.cancel()
  }

  onPointerleave(event) {
    if (!this.state && event.pointerType !== "touch") this.handlers.leave?.()
  }

  onWheel(event) {
    if (event.ctrlKey || event.metaKey) {
      if (!this.handlers.zoom) return

      event.preventDefault()
      const rate = event.deltaMode === 1 ? WHEEL_LINE_ZOOM_RATE : WHEEL_ZOOM_RATE
      this.handlers.zoom(Math.exp(event.deltaY * rate), event)
      return
    }

    const sideways = Math.abs(event.deltaX) > Math.abs(event.deltaY)
    if (!sideways && !event.shiftKey) return
    if (!this.handlers.pan) return

    event.preventDefault()
    const delta = (sideways ? event.deltaX : event.deltaY) * (event.deltaMode === 1 ? WHEEL_LINE_HEIGHT : 1)
    this.handlers.pan(-delta, 0)
    this.handlers.panEnd?.()
  }

  onDoubleClick(event) {
    this.handlers.doubleClick?.(event)
  }

  startPinch() {
    const [first, second] = [...this.pointers.values()]
    if (this.state?.mode === "brush") this.handlers.cancel?.("brush")
    this.state = {
      mode: "pinch",
      distance: Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1,
      center: { clientX: (first.clientX + second.clientX) / 2, clientY: (first.clientY + second.clientY) / 2 }
    }
    this.handlers.pinchStart?.(this.state.center)
  }

  movePinch() {
    if (this.pointers.size < 2) return

    const [first, second] = [...this.pointers.values()]
    const distance = Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1
    this.handlers.pinch?.(this.state.distance / distance)
  }

  capturePointer(pointerId) {
    try {
      this.element.setPointerCapture(pointerId)
    } catch {
      return false
    }
    return true
  }

  finish(callback) {
    this.state = null
    callback()
  }
}
