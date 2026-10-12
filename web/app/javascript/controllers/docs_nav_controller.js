import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["body", "toc"]

  connect() {
    if (!this.hasTocTarget || !this.hasBodyTarget) return

    const sections = [...this.bodyTarget.querySelectorAll(".doc-sec[id]")]
    this.observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) this.setCurrent(entry.target.id)
      })
    }, { rootMargin: "0px 0px -70% 0px" })
    sections.forEach((section) => this.observer.observe(section))
    if (sections[0]) this.setCurrent(location.hash.slice(1) || sections[0].id)
  }

  disconnect() {
    this.observer?.disconnect()
  }

  setCurrent(id) {
    this.tocTarget.querySelectorAll("a").forEach((link) => {
      link.toggleAttribute("aria-current", link.dataset.id === id)
    })
  }

  go(event) {
    const link = event.target.closest("a[href^='#']")
    if (!link || !this.element.contains(link)) return

    const id = link.getAttribute("href").slice(1)
    const section = document.getElementById(id)
    if (!section) return

    event.preventDefault()
    section.scrollIntoView({ behavior: this.scrollBehavior, block: "start" })
    history.replaceState(history.state, "", `#${id}`)
    this.setCurrent(id)
  }

  get scrollBehavior() {
    return matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
  }
}
