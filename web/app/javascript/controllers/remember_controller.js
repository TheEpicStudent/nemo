import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { key: String, open: Boolean }

  connect() {
    const storedOpen = this.storedOpen
    if (storedOpen !== null) this.element.open = storedOpen
  }

  persist() {
    if (!this.hasKeyValue) return

    try {
      localStorage.setItem(this.store, this.element.open ? "1" : "0")
    } catch {
      // a private window or blocked site data, so the default stands
    }
  }

  get store() {
    return `mn-open-${this.keyValue}`
  }

  get storedOpen() {
    if (!this.hasKeyValue) return null

    try {
      const stored = localStorage.getItem(this.store)
      return stored === null ? null : stored === "1"
    } catch {
      return null
    }
  }
}
