import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["start", "ask", "go"]

  ask() {
    this.startTarget.hidden = true
    this.askTarget.hidden = false
    if (this.hasGoTarget) this.goTarget.focus()
  }

  cancel() {
    if (this.askTarget.hidden) return

    this.askTarget.hidden = true
    this.startTarget.hidden = false
    this.startTarget.focus()
  }
}
