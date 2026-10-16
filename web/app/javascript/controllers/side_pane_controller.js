import { Controller } from "@hotwired/stimulus"
import { modalsOpen, popupOpen, aboveOpen } from "lib/layers"

export default class extends Controller {
  connect() {
    this.onKey = this.onKey.bind(this)
    this.onLoad = this.onLoad.bind(this)
    document.addEventListener("keydown", this.onKey)
    this.element.addEventListener("turbo:frame-load", this.onLoad)
  }

  disconnect() {
    document.removeEventListener("keydown", this.onKey)
    this.element.removeEventListener("turbo:frame-load", this.onLoad)
  }

  onLoad() {
    const rowId = this.element.querySelector("[data-row-id]")?.dataset.rowId || this.element.dataset.rowId
    document.dispatchEvent(new CustomEvent("side-pane:opened", { detail: { rowId } }))
  }

  close() {
    if (this.element.matches(":empty")) return

    this.element.innerHTML = ""
    this.element.removeAttribute("src")
    this.clearEventParam()
    document.dispatchEvent(new CustomEvent("side-pane:closed"))
  }

  clearEventParam() {
    const url = new URL(window.location.href)
    if (!url.searchParams.has("event")) return

    url.searchParams.delete("event")
    window.history.replaceState(window.history.state, "", url)
  }

  onKey(event) {
    if (event.key !== "Escape" || event.defaultPrevented || this.element.matches(":empty")) return
    if (aboveOpen() || popupOpen() || modalsOpen() > 0) return

    this.close()
  }
}
