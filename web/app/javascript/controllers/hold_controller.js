import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { duration: { type: Number, default: 1200 } }

  connect() {
    this.onClick = this.onClick.bind(this)
    this.element.addEventListener("click", this.onClick, true)
    this.element.style.setProperty("--hold-ms", `${this.durationValue}ms`)
  }

  disconnect() {
    this.element.removeEventListener("click", this.onClick, true)
    this.release()
  }

  press(event) {
    if (event.button !== 0) return

    this.element.classList.add("is-holding")
    this.timer = setTimeout(() => this.complete(), this.durationValue)
  }

  release() {
    clearTimeout(this.timer)
    this.timer = null
    this.element.classList.remove("is-holding")
  }

  complete() {
    this.release()
    this.armed = true
    this.element.click()
    this.armed = false
    this.swallowReleaseClick()
  }

  swallowReleaseClick() {
    const swallow = (event) => {
      event.preventDefault()
      event.stopImmediatePropagation()
    }
    const stop = () => setTimeout(() => window.removeEventListener("click", swallow, true), 0)
    window.addEventListener("click", swallow, true)
    window.addEventListener("pointerup", stop, { once: true })
    window.addEventListener("pointercancel", stop, { once: true })
  }

  onClick(event) {
    if (this.armed || event.detail === 0) return

    event.preventDefault()
    event.stopImmediatePropagation()
  }
}
