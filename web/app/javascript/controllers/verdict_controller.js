import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["a", "b", "pair", "choice", "note"]

  select(event) {
    const button = event.target.closest("[data-verdict-a]")
    if (!button) return

    this.aTarget.value = button.dataset.verdictA
    this.bTarget.value = button.dataset.verdictB
    this.pairTarget.textContent = button.dataset.verdictNames
    this.choiceTargets.forEach((choice) => { choice.checked = choice.value === (button.dataset.verdictWas || "") })
    this.noteTarget.value = button.dataset.verdictNote || ""
  }
}
