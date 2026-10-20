import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["row"]

  connect() {
    this.onDragStart = this.onDragStart.bind(this)
    this.onDragOver = this.onDragOver.bind(this)
    this.onDrop = this.onDrop.bind(this)
    this.onDragEnd = this.onDragEnd.bind(this)
    this.element.addEventListener("dragstart", this.onDragStart)
    this.element.addEventListener("dragover", this.onDragOver)
    this.element.addEventListener("drop", this.onDrop)
    this.element.addEventListener("dragend", this.onDragEnd)
  }

  disconnect() {
    this.element.removeEventListener("dragstart", this.onDragStart)
    this.element.removeEventListener("dragover", this.onDragOver)
    this.element.removeEventListener("drop", this.onDrop)
    this.element.removeEventListener("dragend", this.onDragEnd)
  }

  grab(event) {
    const row = event.currentTarget.closest("tr")
    if (!row) return

    row.draggable = true
    window.addEventListener("pointerup", () => { if (!this.dragged) row.draggable = false }, { once: true })
  }

  onDragStart(event) {
    const row = event.target.closest("tr")
    if (!row || !this.rowTargets.includes(row)) return

    this.dragged = row
    this.startIndex = this.rowTargets.indexOf(row)
    event.dataTransfer.effectAllowed = "move"
    event.dataTransfer.setData("text/plain", row.dataset.rowSortUrl)
    row.classList.add("is-dragging")
  }

  onDragOver(event) {
    if (!this.dragged) return

    const row = event.target.closest("tr")
    if (!row || row === this.dragged || !this.rowTargets.includes(row)) return

    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    const box = row.getBoundingClientRect()
    const after = event.clientY > box.top + box.height / 2
    row.parentNode.insertBefore(this.dragged, after ? row.nextSibling : row)
  }

  onDrop(event) {
    if (this.dragged) event.preventDefault()
  }

  onDragEnd() {
    const row = this.dragged
    if (!row) return

    this.dragged = null
    row.draggable = false
    row.classList.remove("is-dragging")
    const index = this.rowTargets.indexOf(row)
    if (index !== this.startIndex) this.submit(row.dataset.rowSortUrl, index)
  }

  submit(url, index) {
    const form = document.createElement("form")
    form.method = "post"
    form.action = url
    form.hidden = true
    form.append(this.field("index", String(index)))
    const token = document.querySelector('meta[name="csrf-token"]')?.content
    if (token) form.append(this.field("authenticity_token", token))
    document.body.append(form)
    form.requestSubmit()
  }

  field(name, value) {
    const input = document.createElement("input")
    input.type = "hidden"
    input.name = name
    input.value = value
    return input
  }
}
