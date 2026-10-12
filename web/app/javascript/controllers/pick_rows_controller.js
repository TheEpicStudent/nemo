import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["box", "all", "bar", "count", "field", "go"]

  connect() {
    this.sync()
  }

  get checkedBoxes() {
    return this.boxTargets.filter((box) => box.checked)
  }

  toggle() {
    this.sync()
  }

  toggleAll() {
    const allChecked = this.allTarget.checked
    this.boxTargets.forEach((box) => {
      box.checked = allChecked
    })
    this.sync()
  }

  sync() {
    const checkedBoxes = this.checkedBoxes
    const count = checkedBoxes.length

    if (this.hasAllTarget) {
      this.allTarget.checked = count > 0 && count === this.boxTargets.length
      this.allTarget.indeterminate = count > 0 && count < this.boxTargets.length
    }

    if (this.hasBarTarget) this.barTarget.hidden = count === 0
    if (this.hasCountTarget) this.countTarget.textContent = String(count)

    this.element.querySelectorAll("[data-picked-row]").forEach((row) => {
      const box = row.querySelector("[data-pick-rows-target='box']")
      row.classList.toggle("is-picked", Boolean(box && box.checked))
    })

    this.syncHiddenFields(checkedBoxes)
    this.syncSubmit()
  }

  syncHiddenFields(checkedBoxes) {
    if (!this.hasFieldTarget) return

    this.fieldTarget.replaceChildren(
      ...checkedBoxes.map((box) => {
        const hiddenInput = document.createElement("input")
        hiddenInput.type = "hidden"
        hiddenInput.name = "user_ids[]"
        hiddenInput.value = box.value
        return hiddenInput
      })
    )
  }

  syncSubmit() {
    if (!this.hasGoTarget) return

    this.goTarget.disabled = this.checkedBoxes.length === 0
  }

  clear() {
    this.boxTargets.forEach((box) => {
      box.checked = false
    })
    this.sync()
  }
}
