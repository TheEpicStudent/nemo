import { Controller } from "@hotwired/stimulus"

const ONLY_REPLIES_CLASS = "only-replies"
const INTERNAL_KIND = "chat"

export default class extends Controller {
  static targets = ["all", "replies"]
  static values = { key: String }

  connect() {
    this.apply = this.apply.bind(this)
    this.element.addEventListener("turbo:frame-load", this.apply)
    this.only = this.storedOnlyReplies
    this.apply()
  }

  disconnect() {
    this.element.removeEventListener("turbo:frame-load", this.apply)
  }

  showAll() {
    this.setOnlyReplies(false)
  }

  onlyReplies() {
    this.setOnlyReplies(true)
  }

  setOnlyReplies(only) {
    this.only = only
    this.persist()
    this.apply()
    this.scrollToBottom()
  }

  apply() {
    if (!this.hasAllTarget || !this.hasRepliesTarget) return

    this.element.classList.toggle(ONLY_REPLIES_CLASS, this.only)
    this.allTarget.setAttribute("aria-pressed", String(!this.only))
    this.repliesTarget.setAttribute("aria-pressed", String(this.only))
    this.syncDayRules()
  }

  syncDayRules() {
    const log = this.log
    if (!log) return

    let rule = null
    let visibleCount = 0
    let total = 0

    for (const node of log.children) {
      if (node.dataset.earlier !== undefined || node.dataset.nothing !== undefined) continue
      if (node.classList.contains("dayrule")) {
        if (rule) rule.hidden = visibleCount === 0
        rule = node
        visibleCount = 0
        continue
      }
      if (node.classList.contains("msg") && !this.isHidden(node)) {
        visibleCount += 1
        total += 1
      }
    }
    if (rule) rule.hidden = visibleCount === 0

    const note = log.querySelector("[data-nothing]")
    if (note) note.hidden = !this.only || total > 0 || log.querySelector(".msg") === null
  }

  isHidden(node) {
    return this.only && node.dataset.kind === INTERNAL_KIND
  }

  scrollToBottom() {
    const log = this.log
    if (log) log.scrollTop = log.scrollHeight
  }

  get log() {
    return this.element.querySelector(".chatscroll")
  }

  get store() {
    return `mn-chat-replies-${this.keyValue}`
  }

  get storedOnlyReplies() {
    try {
      return localStorage.getItem(this.store) === "1"
    } catch {
      return false
    }
  }

  persist() {
    try {
      localStorage.setItem(this.store, this.only ? "1" : "0")
    } catch {
      return
    }
  }
}
