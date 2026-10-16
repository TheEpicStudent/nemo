import { Controller } from "@hotwired/stimulus"

const WIDTH_COOKIE = "queuew"
const DRAGGING = "sidebar-dragging"
const MOBILE = "(max-width: 899px)"
const MIN_WIDTH_PX = 280
const MAX_WIDTH_PX = 620

export default class extends Controller {
  connect() {
    this.root = document.documentElement
    this.pane = this.element.querySelector(".pane:not(.cpane)")
    if (!this.pane) return

    this.mobile = window.matchMedia(MOBILE)
    const width = parseInt(this.storedWidth(), 10)
    if (width >= MIN_WIDTH_PX && width <= MAX_WIDTH_PX) this.root.style.setProperty("--queue-w", `${width}px`)
  }

  disconnect() {
    this.root?.classList.remove(DRAGGING)
  }

  drag(event) {
    if (this.mobile.matches || event.button !== 0) return

    event.preventDefault()
    this.handle = event.currentTarget
    this.from = event.clientX
    this.startWidth = this.pane.getBoundingClientRect().width
    this.handle.setPointerCapture(event.pointerId)
    this.root.classList.add(DRAGGING)
  }

  move(event) {
    if (this.from == null) return

    const width = Math.min(MAX_WIDTH_PX, Math.max(MIN_WIDTH_PX, this.startWidth + event.clientX - this.from))
    this.root.style.setProperty("--queue-w", `${Math.round(width)}px`)
  }

  drop(event) {
    if (this.from == null) return

    this.handle?.releasePointerCapture?.(event.pointerId)
    this.root.classList.remove(DRAGGING)
    this.from = null
    this.handle = null

    const width = parseInt(this.root.style.getPropertyValue("--queue-w"), 10)
    if (width) document.cookie = `${WIDTH_COOKIE}=${width}; path=/; max-age=31536000; samesite=lax`
  }

  storedWidth() {
    return document.cookie
      .split("; ")
      .find((pair) => pair.startsWith(`${WIDTH_COOKIE}=`))
      ?.split("=")[1]
  }
}
