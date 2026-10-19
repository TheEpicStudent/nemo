import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["field", "pill", "send", "recipient", "anon", "drop"]
  static values = { reporter: Boolean, reporterLabel: String, case: String, noteUrl: String, replyUrl: String }

  connect() {
    this.anonymous = false
    this.onSubmitEnd = this.onSubmitEnd.bind(this)
    this.element.addEventListener("turbo:submit-end", this.onSubmitEnd)
    this.setRecipient(false)
    this.resizeField()
  }

  disconnect() {
    this.element.removeEventListener("turbo:submit-end", this.onSubmitEnd)
  }

  onSubmitEnd(event) {
    if (!event.detail?.success) return

    this.fieldTarget.value = ""
    this.setRecipient(false)
    this.resizeField()
    this.fieldTarget.focus()
  }

  focus() {
    this.fieldTarget.focus()
  }

  type() {
    const prefixMatch = /^(~?)([?>])\s?/.exec(this.fieldTarget.value)

    if (prefixMatch && this.reporterValue && !this.toReporter) {
      this.fieldTarget.value = this.fieldTarget.value.slice(prefixMatch[0].length)
      this.setRecipient(true, prefixMatch[1] === "~")
    } else if (this.toReporter && !this.anonymous && /^~\s?/.test(this.fieldTarget.value)) {
      this.fieldTarget.value = this.fieldTarget.value.replace(/^~\s?/, "")
      this.setRecipient(true, true)
    }

    this.resizeField()
  }

  keys(event) {
    if (event.defaultPrevented) return

    if (event.key === "Enter" && !event.shiftKey && !this.mentionPopupOpen()) {
      event.preventDefault()
      if (!this.sendTarget.disabled && this.fieldTarget.value.trim()) {
        this.element.requestSubmit()
      }
      return
    }

    if (event.key === "Backspace" && this.toReporter && this.caretAtStart()) {
      event.preventDefault()
      this.setRecipient(false)
    }
  }

  clearRecipient(event) {
    event.stopPropagation()
    this.setRecipient(false)
    this.fieldTarget.focus()
  }

  setRecipient(atReporter, anonymous = false) {
    this.toReporter = atReporter
    this.anonymous = atReporter && anonymous
    this.pillTarget.hidden = false
    this.pillTarget.dataset.mode = atReporter ? "reporter" : "team"
    this.dropTarget.hidden = !atReporter
    this.recipientTarget.textContent = atReporter
      ? `${this.replyTarget()} · ${this.anonymous ? "anonymous" : "signed"}`
      : "internal"
    this.anonTarget.value = this.anonymous ? "1" : ""
    this.element.action = atReporter ? this.replyUrlValue : this.noteUrlValue
    this.sendTarget.setAttribute("aria-label", atReporter ? "Send to reporter" : "Send to team")
  }

  replyTarget() {
    const name = this.reporterLabelValue || "reporter"
    return this.caseValue ? `${name}, case ${this.caseValue}` : name
  }

  mentionPopupOpen() {
    const pop = this.element.querySelector('[data-mention-target="pop"]')
    return pop ? pop.matches(":popover-open") : false
  }

  caretAtStart() {
    return this.fieldTarget.selectionStart === 0 && this.fieldTarget.selectionEnd === 0
  }

  resizeField() {
    const field = this.fieldTarget
    field.style.height = "auto"
    field.style.height = `${Math.min(field.scrollHeight, 160)}px`
  }
}
