import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  down(event) {
    const input = event.currentTarget.querySelector("input[type=radio]")
    this.initiallyChecked = input ? input.checked : false
  }

  press(event) {
    const input = event.currentTarget.querySelector("input[type=radio]")
    if (!input || !this.initiallyChecked) return

    event.preventDefault()
    this.initiallyChecked = false
    input.checked = false
    input.dispatchEvent(new Event("change", { bubbles: true }))
  }
}
