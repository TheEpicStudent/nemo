import { Controller } from "@hotwired/stimulus"

const OPEN_DURATION = 340
const CLOSE_DURATION = 220
const FADE_DURATION = 160
const OPEN_EASING = "cubic-bezier(0.16, 1, 0.3, 1)"
const CLOSE_EASING = "cubic-bezier(0.4, 0, 0.2, 1)"
const PANEL_RADIUS = "14px"
const FULL_CLIP = `inset(0px 0px 0px 0px round ${PANEL_RADIUS})`
const ESCAPE_DEDUPE_MS = 80

export default class extends Controller {
  static targets = ["dialog", "panel", "title", "subtitle", "body", "plot"]

  connect() {
    this.dialog = this.dialogTarget
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)")
    this.onClick = this.onClick.bind(this)
    this.onKeydown = this.onKeydown.bind(this)
    this.onPointerdown = this.onPointerdown.bind(this)
    this.onCancel = this.onCancel.bind(this)
    this.onClose = this.onClose.bind(this)
    this.element.addEventListener("click", this.onClick)
    document.addEventListener("keydown", this.onKeydown)
    this.dialog.addEventListener("pointerdown", this.onPointerdown)
    this.dialog.addEventListener("cancel", this.onCancel)
    this.dialog.addEventListener("close", this.onClose)
  }

  disconnect() {
    this.element.removeEventListener("click", this.onClick)
    document.removeEventListener("keydown", this.onKeydown)
    this.dialog.removeEventListener("pointerdown", this.onPointerdown)
    this.dialog.removeEventListener("cancel", this.onCancel)
    this.dialog.removeEventListener("close", this.onClose)
    if (this.dialog.open) this.dialog.close()
    this.reset()
  }

  open(card, trigger = null) {
    if (!card || this.dialog.open) return

    this.card = card
    this.opener = trigger || document.activeElement
    this.fillHeader(card)
    this.dialog.showModal()
    this.animateOpen()
    this.panelTarget.focus({ preventScroll: true })
  }

  close() {
    if (!this.dialog.open || this.closing) return

    this.closing = true
    const clip = this.cardClip()
    this.fadeBackdrop()
    const animation = clip
      ? this.panelTarget.animate(
        [{ clipPath: FULL_CLIP }, { clipPath: clip, opacity: 0.6 }],
        { duration: CLOSE_DURATION, easing: CLOSE_EASING, fill: "forwards" })
      : this.panelTarget.animate(
        [{ opacity: 1 }, { opacity: 0, transform: "scale(0.985)" }],
        { duration: this.duration(FADE_DURATION), fill: "forwards" })
    animation.finished.catch(() => {}).then(() => this.finishClose())
  }

  dismiss() {
    this.close()
  }

  finishClose() {
    this.closing = false
    if (this.dialog.open) this.dialog.close()
  }

  onClick(event) {
    if (event.target === this.dialog) {
      if (this.pressedBackdrop) this.close()
      return
    }

    const trigger = event.target.closest("[data-explore]")
    if (!trigger || this.dialog.contains(trigger)) return

    event.preventDefault()
    this.open(trigger.closest(".card"), trigger)
  }

  onPointerdown(event) {
    this.pressedBackdrop = event.target === this.dialog
  }

  onKeydown(event) {
    if (event.key !== "Escape" || !this.dialog.open || event.defaultPrevented) return

    event.preventDefault()
    this.escapedAt = performance.now()
    this.dismiss()
  }

  onCancel(event) {
    event.preventDefault()
    if (performance.now() - (this.escapedAt || 0) > ESCAPE_DEDUPE_MS) this.dismiss()
  }

  onClose() {
    this.closing = false
    const opener = this.opener
    this.reset()
    if (opener?.isConnected && typeof opener.focus === "function") opener.focus({ preventScroll: true })
  }

  reset() {
    this.backdropAnimation?.cancel()
    this.backdropAnimation = null
    this.panelTarget.getAnimations().forEach((animation) => animation.cancel())
    this.bodyTarget.getAnimations().forEach((animation) => animation.cancel())
    this.plotTarget.replaceChildren()
    this.card = null
    this.opener = null
  }

  fillHeader(card) {
    const title = card.querySelector(".card-title")?.textContent.trim() || ""
    const subtitle = card.querySelector(".card-sub")?.textContent.trim() || ""
    this.titleTarget.textContent = title
    this.subtitleTarget.textContent = subtitle
    this.subtitleTarget.hidden = !subtitle
  }

  animateOpen() {
    const clip = this.cardClip()
    if (!clip) {
      this.panelTarget.animate(
        [{ opacity: 0, transform: "scale(0.985)" }, { opacity: 1, transform: "none" }],
        { duration: this.duration(FADE_DURATION), easing: "ease-out" })
      return
    }

    this.panelTarget.animate([{ clipPath: clip }, { clipPath: FULL_CLIP }],
      { duration: OPEN_DURATION, easing: OPEN_EASING })
    this.bodyTarget.animate([{ opacity: 0.35 }, { opacity: 1 }],
      { duration: OPEN_DURATION - 60, easing: "ease-out" })
  }

  fadeBackdrop() {
    try {
      this.backdropAnimation = this.dialog.animate([{ opacity: 1 }, { opacity: 0 }],
        { duration: this.duration(CLOSE_DURATION), pseudoElement: "::backdrop", fill: "forwards" })
    } catch {
      this.backdropAnimation = null
    }
  }

  cardClip() {
    if (this.reducedMotion.matches || !this.card?.isConnected) return null

    const card = this.card.getBoundingClientRect()
    const panel = this.panelTarget.getBoundingClientRect()
    if (!card.width || card.bottom < 0 || card.top > window.innerHeight) return null

    const top = Math.max(0, card.top - panel.top)
    const right = Math.max(0, panel.right - card.right)
    const bottom = Math.max(0, panel.bottom - card.bottom)
    const left = Math.max(0, card.left - panel.left)
    return `inset(${top}px ${right}px ${bottom}px ${left}px round ${PANEL_RADIUS})`
  }

  duration(ms) {
    return this.reducedMotion.matches ? 1 : ms
  }
}
