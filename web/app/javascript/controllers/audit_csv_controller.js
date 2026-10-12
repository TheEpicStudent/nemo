import { Controller } from "@hotwired/stimulus"

const RESET_MS = 1600

export default class extends Controller {
  static targets = ["label"]
  static values = { url: String }

  async copy() {
    const original = this.labelTarget.textContent
    try {
      const response = await fetch(this.urlValue, { headers: { Accept: "text/csv" } })
      if (!response.ok) throw new Error(response.status)

      const csv = await response.text()
      await navigator.clipboard.writeText(csv)
      const rows = Math.max(csv.split("\r\n").length - 1, 0)
      this.show(`Copied ${rows} ${rows === 1 ? "row" : "rows"}`, original)
    } catch {
      this.show("Copy failed", original)
    }
  }

  show(text, original) {
    clearTimeout(this.timer)
    this.labelTarget.textContent = text
    this.timer = setTimeout(() => { this.labelTarget.textContent = original }, RESET_MS)
  }
}
