import { Controller } from "@hotwired/stimulus"
import { modalsOpen, popupOpen, aboveOpen } from "lib/layers"

const TYPING = "input, textarea, select, [contenteditable]"

export default class extends Controller {
  static targets = ["choice"]

  connect() {
    this.onKey = this.onKey.bind(this)
    document.addEventListener("keydown", this.onKey)
  }

  disconnect() {
    document.removeEventListener("keydown", this.onKey)
  }

  onKey(event) {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return
    if (event.target.closest?.(TYPING) || aboveOpen() || popupOpen() || modalsOpen() > 0) return

    const key = event.key.toLowerCase()
    const choice = this.choiceTargets.find((button) => button.dataset.key === key)
    if (!choice) return

    event.preventDefault()
    if (choice.type === "submit") {
      this.element.requestSubmit(choice)
    } else {
      choice.click()
    }
  }
}
