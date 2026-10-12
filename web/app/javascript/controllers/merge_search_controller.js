import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["field"]
  static values = { url: String, wait: { type: Number, default: 200 } }

  search() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.fetch(), this.waitValue)
  }

  fetch() {
    const frame = document.getElementById("merge-body")
    if (!frame) return

    const query = this.fieldTarget.value.trim()
    frame.src = query ? `${this.urlValue}?q=${encodeURIComponent(query)}` : this.urlValue
  }

  disconnect() {
    clearTimeout(this.timer)
  }
}
