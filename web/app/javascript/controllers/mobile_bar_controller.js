import { Controller } from "@hotwired/stimulus"

const NARROW = "(max-width: 899px)"

export default class extends Controller {
  connect() {
    this.narrow = window.matchMedia(NARROW)
    this.onChange = () => this.relocateActions()
    this.narrow.addEventListener("change", this.onChange)
    this.relocateActions()
  }

  disconnect() {
    this.narrow?.removeEventListener("change", this.onChange)
  }

  relocateActions() {
    const bar = this.element.querySelector(".topbar-actions")
    const actions = this.element.querySelector(".ractions")
    const top = this.element.querySelector(".rhead > .row-top")
    if (!bar || !actions) return

    const container = this.narrow.matches ? bar : top
    if (container && actions.parentElement !== container) container.append(actions)
  }
}
