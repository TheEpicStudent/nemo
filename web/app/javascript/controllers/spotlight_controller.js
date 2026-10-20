import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  move(event) {
    const tile = event.target.closest(".metric")
    if (!tile || !this.element.contains(tile)) return

    const box = tile.getBoundingClientRect()
    tile.style.setProperty("--spot-x", `${event.clientX - box.left}px`)
    tile.style.setProperty("--spot-y", `${event.clientY - box.top}px`)
  }

  leave() {
    this.element.querySelectorAll(".metric").forEach((tile) => {
      tile.style.removeProperty("--spot-x")
      tile.style.removeProperty("--spot-y")
    })
  }
}
