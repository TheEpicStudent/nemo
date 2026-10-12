import { Controller } from "@hotwired/stimulus"

const POLL_INTERVAL_MS = 5000
const PUSH_FALLBACK_MS = 30000
const PUSH_DEBOUNCE_MS = 300
const HIGHLIGHT_MS = 2400

export default class extends Controller {
  static values = { url: String, watch: Object }

  connect() {
    this.knownIds = this.rowIds()
    this.stale = false
    this.onLoad = () => this.highlightNewRows()
    this.onAuditEvent = (event) => this.receive(event.detail || {})
    this.onVisibility = () => { if (!document.hidden && this.stale) this.refresh() }
    this.element.addEventListener("turbo:frame-load", this.onLoad)
    document.addEventListener("audit:event", this.onAuditEvent)
    document.addEventListener("visibilitychange", this.onVisibility)
    this.timer = setInterval(() => this.refresh(), this.pushed ? PUSH_FALLBACK_MS : POLL_INTERVAL_MS)
  }

  disconnect() {
    clearInterval(this.timer)
    clearTimeout(this.pending)
    this.element.removeEventListener("turbo:frame-load", this.onLoad)
    document.removeEventListener("audit:event", this.onAuditEvent)
    document.removeEventListener("visibilitychange", this.onVisibility)
  }

  get pushed() {
    return Array.isArray(this.watchValue.sources)
  }

  receive(event) {
    if (!this.pushed || !this.matches(event)) return

    clearTimeout(this.pending)
    this.pending = setTimeout(() => this.refresh(), PUSH_DEBOUNCE_MS)
  }

  matches(event) {
    const watch = this.watchValue
    if (event.source && !watch.sources.includes(event.source)) return false
    if (event.truncated) return true

    return this.overlaps(watch.actions, event.actions) &&
      this.overlaps(watch.actors, event.actors) &&
      this.overlaps(watch.subjects, event.subjects)
  }

  overlaps(watched, received) {
    if (!Array.isArray(watched)) return true

    return (received || []).some((value) => watched.includes(value))
  }

  refresh() {
    if (document.hidden || this.element.querySelector("details[open]")) {
      this.stale = true
      return
    }

    this.stale = false
    this.knownIds = this.rowIds()
    if (this.element.getAttribute("src") === this.urlValue) {
      this.element.reload()
    } else {
      this.element.src = this.urlValue
    }
  }

  highlightNewRows() {
    this.element.querySelectorAll("tr[data-row-id]").forEach((row) => {
      if (this.knownIds.has(row.dataset.rowId)) return

      row.classList.add("audit-row-new")
      setTimeout(() => row.classList.remove("audit-row-new"), HIGHLIGHT_MS)
    })
    this.knownIds = this.rowIds()
  }

  rowIds() {
    return new Set([...this.element.querySelectorAll("tr[data-row-id]")].map((row) => row.dataset.rowId))
  }
}
