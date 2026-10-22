import { Controller } from "@hotwired/stimulus"
import TextType from "react_bits/text_type"

const CURRENT_CLASS = "is-current"
const TYPER = {
  typingSpeed: 42,
  deletingSpeed: 18,
  pauseDuration: 2400,
  initialDelay: 1600,
  cursorStyle: "block",
  loop: true,
  startOnVisible: true
}

export default class extends Controller {
  static targets = ["command", "composer"]

  connect() {
    const examples = this.commandTargets.map((command) => command.dataset.example)
    this.select(0)
    this.typer = new TextType(this.composerTarget, {
      ...TYPER,
      text: examples,
      onSentenceComplete: (_, index) => this.select((index + 1) % examples.length)
    })
  }

  disconnect() {
    this.typer?.destroy()
    this.typer = null
  }

  select(index) {
    this.commandTargets.forEach((command, position) => command.classList.toggle(CURRENT_CLASS, position === index))
  }
}
