import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["role", "scope", "channels", "area", "empty", "note", "scopes"]
  static values = { baselines: Object }

  connect() {
    this.sync()
  }

  sync() {
    const role = this.selectedRole()
    const baselineKeys = new Set(this.baselinesValue[role] || [])

    this.channelsTarget.hidden = role === ""

    let visibleCount = 0
    for (const row of this.scopeTargets) {
      const inBaseline = baselineKeys.has(row.dataset.key)
      row.hidden = inBaseline
      if (inBaseline) {
        const box = row.querySelector("input[type=checkbox]")
        if (box) box.checked = false
      } else {
        visibleCount += 1
      }
    }

    for (const area of this.areaTargets) {
      const rows = this.scopeTargets.filter((row) => row.dataset.area === area.dataset.area)
      area.hidden = rows.every((row) => row.hidden)
    }

    if (this.hasEmptyTarget) this.emptyTarget.hidden = visibleCount > 0
    if (this.hasScopesTarget) this.scopesTarget.hidden = visibleCount === 0
    if (this.hasNoteTarget) this.noteTarget.textContent = this.roleNote(role)
  }

  roleNote(role) {
    const baselineCount = (this.baselinesValue[role] || []).length
    if (!role) return "A member. Reads the overview and public channels."
    if (baselineCount === 0) return ""
    return `Carries ${baselineCount} capabilit${baselineCount === 1 ? "y" : "ies"} on its own.`
  }

  selectedRole() {
    const checkedRole = this.roleTargets.find((input) => input.checked)
    return checkedRole ? checkedRole.value : ""
  }
}
