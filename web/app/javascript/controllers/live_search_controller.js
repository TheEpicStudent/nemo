import { Controller } from "@hotwired/stimulus"

let pendingCaret = null

export default class extends Controller {
  static values = { wait: { type: Number, default: 250 } }

  connect() {
    const caretPosition = pendingCaret
    pendingCaret = null
    if (caretPosition == null) return

    const field = this.field
    if (!field) return

    field.focus()
    const caret = Math.min(caretPosition, field.value.length)
    field.setSelectionRange(caret, caret)
  }

  disconnect() {
    clearTimeout(this.timer)
  }

  go() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      const field = this.field
      if (field && document.activeElement === field) {
        pendingCaret = field.selectionStart ?? field.value.length
      }
      this.element.requestSubmit()
    }, this.waitValue)
  }

  get field() {
    return this.element.querySelector("input[type=search], .queue-search-input")
  }
}
