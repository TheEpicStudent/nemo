import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["query", "row", "empty", "list"]
  static values = {
    wait: { type: Number, default: 400 },
    min: { type: Number, default: 2 },
    url: String,
    listId: { type: String, default: "member-listbox" },
    label: { type: String, default: "Members" }
  }

  connect() {
    this.onKey = (event) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return
      if (event.target.matches("input, textarea, select, [contenteditable='true']")) return

      event.preventDefault()
      this.queryTarget.focus()
    }
    document.addEventListener("keydown", this.onKey)
    this.serverFiltered = this.queryTarget.value.trim().length > 0
  }

  disconnect() {
    document.removeEventListener("keydown", this.onKey)
    clearTimeout(this.timer)
    this.request?.abort()
  }

  applyTerm(event) {
    this.queryTarget.value = event.params.term || ""
    this.filter()
  }

  filter() {
    const term = this.queryTarget.value.trim().toLocaleLowerCase()
    let visibleCount = 0

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches

    this.rowTargets.forEach((row) => {
      const matches = !term || row.textContent.toLocaleLowerCase().includes(term)
      const changed = matches === row.hidden
      row.hidden = !matches
      if (matches && changed && !reducedMotion) {
        row.animate(
          [{ opacity: 0, transform: "translateY(2px)" }, { opacity: 1, transform: "none" }],
          { duration: 150, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }
        )
      }
      if (matches) visibleCount += 1
    })

    if (this.hasEmptyTarget) this.emptyTarget.hidden = visibleCount > 0

    clearTimeout(this.timer)
    if (!this.hasUrlValue) return
    if (visibleCount === 0 && term.length >= this.minValue) {
      this.timer = setTimeout(() => this.search(term), this.waitValue)
    } else if (!term && (this.replaced || this.serverFiltered)) {
      this.timer = setTimeout(() => this.search(""), this.waitValue)
    }
  }

  async search(term) {
    this.request?.abort()
    this.request = new AbortController()
    const params = new URLSearchParams(new FormData(this.queryTarget.form))
    params.set("q", term)

    let html
    try {
      const response = await fetch(`${this.urlValue}?${params}`, {
        headers: { Accept: "text/html" }, signal: this.request.signal,
      })
      if (!response.ok) return
      html = await response.text()
    } catch {
      return
    }
    if (this.queryTarget.value.trim().toLocaleLowerCase() !== term) return

    this.replace(html)
    this.replaced = term.length > 0
    this.serverFiltered = this.replaced
  }

  replace(html) {
    const container = document.createElement("div")
    container.innerHTML = html
    const next = container.querySelector("template[data-expand-next]")
    next?.remove()

    let listbox = this.listTarget.querySelector(`#${this.listIdValue}`)
    if (!listbox) {
      this.listTarget.querySelectorAll(".empty:not(.pane-filter-empty)").forEach((el) => el.remove())
      listbox = document.createElement("div")
      listbox.id = this.listIdValue
      listbox.setAttribute("role", "listbox")
      listbox.setAttribute("aria-label", this.labelValue)
      this.listTarget.prepend(listbox)
    }
    listbox.replaceChildren(...container.children)

    this.listTarget.querySelector(".pane-more")?.remove()
    if (next) {
      const expander = document.createElement("div")
      expander.className = "pane-more"
      expander.setAttribute("aria-hidden", "true")
      expander.dataset.controller = "expand"
      expander.dataset.expandIntoValue = this.listIdValue
      expander.dataset.expandUrlValue = next.dataset.expandNext
      expander.innerHTML = '<i class="dot run"></i>'
      listbox.after(expander)
    }

    if (this.hasEmptyTarget) this.emptyTarget.hidden = this.rowTargets.length > 0
  }
}
