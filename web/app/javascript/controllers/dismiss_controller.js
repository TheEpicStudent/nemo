import { Controller } from "@hotwired/stimulus"

const POPUPS = "details.menu[open], details.picker[open]"

export default class extends Controller {
  connect() {
    this.onDocumentClick = this.onDocumentClick.bind(this)
    this.escape = this.escape.bind(this)
    document.addEventListener("click", this.onDocumentClick)
    document.addEventListener("keydown", this.escape)
  }

  disconnect() {
    document.removeEventListener("click", this.onDocumentClick)
    document.removeEventListener("keydown", this.escape)
  }

  onDocumentClick(event) {
    for (const popup of this.element.querySelectorAll(POPUPS)) {
      if (!popup.contains(event.target)) popup.removeAttribute("open")
    }
  }

  escape(event) {
    if (event.key !== "Escape") return

    for (const popup of this.element.querySelectorAll(POPUPS)) {
      popup.removeAttribute("open")
    }
  }
}
