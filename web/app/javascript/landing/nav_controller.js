import { Controller } from "@hotwired/stimulus"

const FLOATING_CLASS = "is-floating"
const THRESHOLD_PX = 8

export default class extends Controller {
  connect() {
    this.onScroll = () => {
      if (this.frame) return
      this.frame = requestAnimationFrame(() => {
        this.frame = null
        this.element.classList.toggle(FLOATING_CLASS, window.scrollY > THRESHOLD_PX)
      })
    }
    window.addEventListener("scroll", this.onScroll, { passive: true })
    this.onScroll()
  }

  disconnect() {
    window.removeEventListener("scroll", this.onScroll)
    cancelAnimationFrame(this.frame)
  }
}
