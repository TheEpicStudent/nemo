import { Controller } from "@hotwired/stimulus"
import { cable } from "@hotwired/turbo-rails"

const HEARTBEAT_INTERVAL_MS = 30_000

export default class extends Controller {
  static values = { case: Number, me: String }

  async connect() {
    this.disconnected = false
    this.hideSelf = this.hideSelf.bind(this)
    this.observer = new MutationObserver(this.hideSelf)
    this.observer.observe(this.element, { childList: true, subtree: true })
    this.hideSelf()

    const subscription = await cable.subscribeTo(
      { channel: "CaseChatPresenceChannel", case_id: this.caseValue }, {}
    )
    if (this.disconnected) return subscription.unsubscribe()

    this.subscription = subscription
    this.heartbeatTimer = setInterval(() => subscription.perform("beat"), HEARTBEAT_INTERVAL_MS)
  }

  disconnect() {
    this.disconnected = true
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer)
    if (this.subscription) this.subscription.unsubscribe()
    if (this.observer) this.observer.disconnect()
  }

  hideSelf() {
    const box = this.element.querySelector(".chat-here")
    if (!box) return

    const otherNames = []
    box.querySelectorAll("[data-user]").forEach((userElement) => {
      const isSelf = userElement.dataset.user === this.meValue
      userElement.hidden = isSelf
      if (!isSelf) otherNames.push(userElement.dataset.name)
    })
    box.hidden = otherNames.length === 0
    box.setAttribute("aria-label", this.presenceLabel(otherNames))
  }

  presenceLabel(names) {
    if (names.length === 0) return ""
    return `Viewing: ${names.join(", ")}`
  }
}
