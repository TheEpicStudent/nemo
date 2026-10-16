import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["option", "accent", "name"]

  connect() {
    this.onTheme = () => this.render()
    document.addEventListener("mn:theme", this.onTheme)
    this.render()
  }

  disconnect() {
    document.removeEventListener("mn:theme", this.onTheme)
  }

  select(event) {
    const key = event.currentTarget.dataset.themeKey
    if (!key) return

    window.MnTheme?.select(key, this.origin(event))
  }

  flip(event) {
    const activeTheme = document.documentElement.getAttribute("data-theme")
    window.MnTheme?.select(activeTheme === "lightsout" ? "light" : "lightsout", this.origin(event))
  }

  tint(event) {
    if (!window.MnTheme) return

    window.MnTheme.tint(!window.MnTheme.state().accent, this.origin(event))
  }

  origin(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const pointer = event.clientX || event.clientY
    return pointer
      ? { x: event.clientX, y: event.clientY }
      : { x: box.left + box.width / 2, y: box.top + box.height / 2 }
  }

  render() {
    if (!window.MnTheme) return

    const { pinned, accent } = window.MnTheme.state()
    const activeTheme = document.documentElement.getAttribute("data-theme")

    this.optionTargets.forEach((el) => {
      const key = el.dataset.themeKey
      el.setAttribute("aria-pressed", key === pinned ? "true" : "false")
      el.classList.toggle("on", key === activeTheme)
      el.classList.toggle("auto", !pinned && key === activeTheme)
    })

    this.accentTargets.forEach((el) => {
      if (el.type === "checkbox") el.checked = Boolean(accent)
      else el.setAttribute("aria-pressed", accent ? "true" : "false")
    })

    this.syncNameLabel(this.optionTargets.find((el) => el.dataset.themeKey === activeTheme), pinned)
  }

  syncNameLabel(option, pinned) {
    if (!option) return

    if (this.hasNameTarget) {
      const label = option.querySelector(".theme-label")?.textContent
      this.nameTarget.textContent = pinned ? label : `${label} · auto`
    }
  }
}
