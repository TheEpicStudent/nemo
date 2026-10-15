import { Controller } from "@hotwired/stimulus"

const CUSTOM = "custom"

export default class extends Controller {
  static targets = ["select", "custom"]

  connect() {
    this.toggle()
  }

  toggle() {
    const custom = this.selectTarget.value === CUSTOM
    this.customTarget.hidden = !custom
    this.customTarget.querySelectorAll("input").forEach((input) => {
      input.disabled = !custom
    })
  }
}
