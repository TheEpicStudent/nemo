import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { url: String }
  static targets = ["fields", "expiry", "channel", "locks", "targetFields", "standing", "why"]

  connect() {
    this.toggleFields()
    this.toggleKindFields()
  }

  reloadStanding() {
    const frame = this.element.querySelector("turbo-frame#action-standing")
    const form = this.element.querySelector("form")
    if (!frame || !form) return

    const params = new URLSearchParams({
      target_user_id: new FormData(form).get("target_user_id") ?? ""
    })
    frame.src = `${this.urlValue}?${params}`
    frame.reload()
  }

  toggleFields() {
    if (!this.hasFieldsTarget) return

    const selectedGuard = this.element.querySelector('input[name="standing_guard_id"]:checked')
    this.fieldsTarget.hidden = Boolean(selectedGuard && selectedGuard.value)
  }

  toggleKindFields() {
    const kind = this.element.querySelector('select[name="type_key"]')?.selectedOptions[0]
    if (!kind) return

    const onThread = kind.dataset.lock === "true"

    if (this.hasExpiryTarget) {
      this.expiryTarget.hidden = onThread || kind.dataset.expires !== "true"
    }
    if (this.hasChannelTarget) {
      this.channelTarget.hidden = onThread || kind.dataset.channel !== "true"
    }
    if (this.hasLocksTarget) this.locksTarget.hidden = !onThread
    if (this.hasTargetFieldsTarget) this.targetFieldsTarget.hidden = onThread
    if (this.hasStandingTarget) this.standingTarget.hidden = onThread
    if (this.hasWhyTarget) this.whyTarget.hidden = onThread
  }
}
