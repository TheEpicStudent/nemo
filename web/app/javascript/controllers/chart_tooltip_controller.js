import { Controller } from "@hotwired/stimulus"

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi)

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")

export default class extends Controller {
  static targets = ["mark"]

  connect() {
    this.element.classList.add("tipped")
    this.tip = document.createElement("div")
    this.tip.className = "tip"
    this.element.appendChild(this.tip)
  }

  disconnect() {
    this.tip?.remove()
  }

  show(event) {
    const mark = event.target.closest("[data-tip]")
    if (!mark) return this.clear()

    let tip_data
    try {
      tip_data = JSON.parse(mark.dataset.tip)
    } catch {
      return this.clear()
    }

    const rows = (tip_data.rows || []).map((r) =>
      `<div class="row"><i${r.tone ? ` style="background:${esc(r.tone)}"` : ""}></i>${
        esc(r.label)}<b>${esc(r.value)}${
        r.of == null ? "" : ` <u>${esc(r.of)}</u>`}</b></div>`).join("")
    const note = tip_data.note ? `<div class="row row-note"><i></i>${esc(tip_data.note)}</div>` : ""

    this.tip.innerHTML = `<div class="t">${esc(tip_data.title)}</div>${rows}${note}`
    this.tip.classList.add("on")
    this.position(mark)
  }

  position(mark) {
    const host = this.element.getBoundingClientRect()
    const at = mark.getBoundingClientRect()
    const tipWidth = this.tip.offsetWidth || 190
    const tipHeight = this.tip.offsetHeight || 60

    let left = at.left - host.left + at.width + 12
    if (left + tipWidth > host.width) left = at.left - host.left - tipWidth - 12
    this.tip.style.left = `${clamp(left, 0, Math.max(0, host.width - tipWidth))}px`
    this.tip.style.top = `${clamp(at.top - host.top + at.height / 2 - tipHeight / 2, 0,
      Math.max(0, host.height - tipHeight))}px`
  }

  clear() {
    this.tip?.classList.remove("on")
  }
}
