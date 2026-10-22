import { Controller } from "@hotwired/stimulus"

const CURRENT_CLASS = "is-current"

export default class extends Controller {
  static targets = ["tab", "shot"]

  select(event) {
    const index = this.tabTargets.indexOf(event.currentTarget)
    if (index < 0) return

    this.tabTargets.forEach((tab, position) => tab.setAttribute("aria-selected", String(position === index)))
    this.shotTargets.forEach((shot, position) => shot.classList.toggle(CURRENT_CLASS, position === index))
  }
}
