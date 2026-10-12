import { Controller } from "@hotwired/stimulus"

const SLOW_AFTER = 10000
const HIGHLIGHT_MS = 1600

export default class extends Controller {
  static targets = ["slow"]

  connect() {
    this.mark()
    this.waitForSlack()
  }

  disconnect() {
    clearTimeout(this.slowTimer)
    clearTimeout(this.highlightTimer)
  }

  get enforcementStatus() {
    return this.element.dataset.enforcementStatus
  }

  mark() {
    if (this.element.dataset.landed !== "true") return

    this.element.classList.add("just-landed")
    this.highlightTimer = setTimeout(() => {
      this.element.classList.remove("just-landed")
    }, HIGHLIGHT_MS)
  }

  waitForSlack() {
    if (this.enforcementStatus !== "pending" || !this.hasSlowTarget) return

    this.slowTimer = setTimeout(() => {
      this.slowTarget.hidden = false
    }, SLOW_AFTER)
  }
}
