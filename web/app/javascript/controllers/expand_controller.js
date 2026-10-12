import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { url: String, into: String, root: { type: String, default: ".pane-list" } }

  connect() {
    this.loading = false
    this.observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) this.load()
    }, { root: this.element.closest(this.rootValue), rootMargin: "320px 0px" })
    this.observer.observe(this.element)
  }

  disconnect() {
    this.observer?.disconnect()
  }

  async load() {
    if (this.loading || !this.urlValue) return
    this.loading = true

    try {
      const response = await fetch(this.urlValue, { headers: { Accept: "text/html" } })
      if (!response.ok) throw new Error(response.status)

      const container = document.createElement("div")
      container.innerHTML = await response.text()
      const next = container.querySelector("template[data-expand-next]")
      next?.remove()

      const list = document.getElementById(this.intoValue)
      if (list) list.append(...container.children)

      if (next) {
        this.urlValue = next.dataset.moreNext
        this.loading = false
        this.observer.unobserve(this.element)
        this.observer.observe(this.element)
      } else {
        this.element.remove()
      }
    } catch {
      this.loading = false
    }
  }
}
