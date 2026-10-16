const VIEWPORT_MARGIN_PX = 12
const MIN_ROOM_BELOW_PX = 160
const ANCHOR_GAP_PX = 5

export function placePop(pop, anchor) {
  const box = anchor.getBoundingClientRect()
  const below = window.innerHeight - box.bottom - VIEWPORT_MARGIN_PX
  const above = box.top - VIEWPORT_MARGIN_PX
  const up = below < MIN_ROOM_BELOW_PX && above > below

  pop.classList.toggle("menu-up", up)
  pop.style.setProperty("--menu-room", `${Math.max(0, Math.round(up ? above : below))}px`)
  if (!pop.hasAttribute("popover")) return

  pop.style.left = "0px"
  pop.style.top = "0px"
  const size = { width: pop.offsetWidth, height: pop.offsetHeight }
  const start = pop.classList.contains("menu-start")
  const left = Math.max(VIEWPORT_MARGIN_PX, Math.min(start ? box.left : box.right - size.width,
    window.innerWidth - VIEWPORT_MARGIN_PX - size.width))
  const top = up ? box.top - size.height - ANCHOR_GAP_PX : box.bottom + ANCHOR_GAP_PX

  pop.style.left = `${Math.round(left)}px`
  pop.style.top = `${Math.round(Math.max(VIEWPORT_MARGIN_PX,
    Math.min(top, window.innerHeight - VIEWPORT_MARGIN_PX - size.height)))}px`
}

export function clearPop(pop) {
  pop.style.removeProperty("--menu-room")
  pop.style.removeProperty("left")
  pop.style.removeProperty("top")
  pop.classList.remove("menu-up")
}
