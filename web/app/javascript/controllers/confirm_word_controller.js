import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { word: String }
  static targets = ["field", "go"]

  connect() {
    this.toggleSubmit()
  }

  toggleSubmit() {
    if (!this.hasGoTarget) return

    const inputWord = this.hasFieldTarget ? this.fieldTarget.value.trim() : ""
    const expectedWord = this.wordValue.trim()
    this.goTarget.disabled = inputWord.toLowerCase() !== expectedWord.toLowerCase()
  }
}
