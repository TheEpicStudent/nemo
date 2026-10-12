import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  show(event) {
    const value = event.target.closest(".cmp-value[data-v]")
    if (!value) return

    this.clear()
    this.element.querySelectorAll(`.cmp-value[data-v="${value.dataset.v}"]`).forEach((match) => match.classList.add("is-hl"))
  }

  clear() {
    this.element.querySelectorAll(".cmp-value.is-hl").forEach((match) => match.classList.remove("is-hl"))
  }
}
