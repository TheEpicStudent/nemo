import { Controller } from "@hotwired/stimulus"

const INTERACTIVE = "a, button, summary, details, input, select, textarea, label"

export default class extends Controller {
  connect() {
    this.selectedId = null
    this.onOpened = (event) => this.select(event.detail?.rowId)
    this.onClosed = () => this.select(null)
    this.onLoad = () => this.mark()
    document.addEventListener("side-pane:opened", this.onOpened)
    document.addEventListener("side-pane:closed", this.onClosed)
    this.element.addEventListener("turbo:frame-load", this.onLoad)
    const pane = document.getElementById("audit-panel")
    this.select(pane && !pane.matches(":empty") ? pane.querySelector("[data-row-id]")?.dataset.rowId : null)
  }

  disconnect() {
    document.removeEventListener("side-pane:opened", this.onOpened)
    document.removeEventListener("side-pane:closed", this.onClosed)
    this.element.removeEventListener("turbo:frame-load", this.onLoad)
  }

  open(event) {
    if (event.target.closest(INTERACTIVE)) return

    const row = event.currentTarget
    const pane = document.getElementById("audit-panel")
    if (!pane || !row.dataset.eventUrl) return

    event.preventDefault()
    pane.src = row.dataset.eventUrl
    this.select(row.dataset.rowId)
  }

  select(rowId) {
    this.selectedId = rowId || null
    this.mark()
  }

  mark() {
    this.element.querySelectorAll("tr[data-row-id]").forEach((row) => {
      if (row.dataset.rowId === this.selectedId) {
        row.setAttribute("aria-selected", "true")
      } else {
        row.removeAttribute("aria-selected")
      }
    })
  }
}
