import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  connect() {
    this.narrow = window.matchMedia("(max-width: 899px)")
    this.onChange = () => this.sync()
    this.narrow.addEventListener("change", this.onChange)
    this.sync()
  }

  disconnect() {
    this.narrow.removeEventListener("change", this.onChange)
  }

  sync() {
    const backButton = this.element.querySelector(".backbtn")
    if (backButton) backButton.hidden = !this.narrow.matches
  }

  show() {
    this.element.dataset.view = "pane"
  }

  hide() {
    this.element.dataset.view = "main"
  }
}
