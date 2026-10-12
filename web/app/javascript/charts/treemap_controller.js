import { TileChart, clip, esc, N, PC } from "charts/tiles"

const CLAMP = 100
const TONES = ["d3", "d2", "d1", "z", "u1", "u2", "u3"]
const TONE_NAMES = {
  d3: "shrank a lot", d2: "shrank", d1: "shrank a little", z: "flat",
  u1: "grew a little", u2: "grew", u3: "grew a lot", na: "new"
}
const FLAT_BAND = 4
const SIZES = { messages: "member messages", prior: "window before" }

const signed = (v) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(0)}%`
const toneColor = (tone) => `var(--dv-${tone})`
const changeOf = (row) => (row.thin || row.pct == null ? null : Number(row.pct))

export default class extends TileChart {
  static values = { total: Number, floor: Number }

  get sizeBy() {
    return this.viewValue.sizeBy === "prior" ? "prior" : "messages"
  }

  get total() {
    return this.hasTotalValue ? this.totalValue : 0
  }

  get floor() {
    return this.hasFloorValue ? this.floorValue : 0
  }

  items() {
    const by = this.sizeBy
    return this.tilesValue
      .map((row, i) => ({ i, row, v: Number(row[by]) || 0 }))
      .filter((item) => item.v > 0)
      .sort((a, b) => b.v - a.v)
  }

  step(row) {
    const pct = changeOf(row)
    if (pct == null) return "na"

    const v = Math.max(-CLAMP, Math.min(CLAMP, pct))
    if (v <= -45) return "d3"
    if (v <= -18) return "d2"
    if (v <= -FLAT_BAND) return "d1"
    if (v < FLAT_BAND) return "z"
    if (v < 18) return "u1"
    if (v < 45) return "u2"
    return "u3"
  }

  toneOf(item) {
    return this.step(item.row)
  }

  seriesOf(item) {
    return this.step(item.row)
  }

  labelMarkup({ row, x, y, w, h }) {
    const label = `#${row.name}`
    const pct = changeOf(row)
    const value = pct == null ? "new" : signed(pct)
    const cx = x + w / 2
    const cap = this.fill ? 22 : 20

    // both lines always; shrink toward the floor until the pair fits the tile
    let nameSize = Math.max(8, Math.min(cap, Math.round(Math.min(w, h) / 3.4)))
    let valSize = Math.max(8, Math.round(nameSize * 0.82))
    while (nameSize > 8 && nameSize + valSize + 4 > h - 6) {
      nameSize -= 1
      valSize = Math.max(8, Math.round(nameSize * 0.82))
    }

    const pair = nameSize + valSize + 4
    const first = y + h / 2 - pair / 2 + nameSize
    const maxWidth = w - 8
    const nameLabel = clip(label, nameSize, maxWidth)
    const valueLabel = clip(value, valSize, maxWidth, 500)

    let text = ""
    if (nameLabel) {
      text += `<text class="t-n" x="${cx.toFixed(1)}" y="${first.toFixed(1)}"
        text-anchor="middle" font-size="${nameSize}">${esc(nameLabel)}</text>`
    }
    if (valueLabel) {
      text += `<text class="t-v" x="${cx.toFixed(1)}" y="${
        (first + valSize + 4).toFixed(1)}" text-anchor="middle"
        font-size="${valSize}">${esc(valueLabel)}</text>`
    }
    return text
  }

  summary() {
    const rows = this.tilesValue
    const top = rows[0]
    const bits = [`Treemap of ${rows.length} tiles, area is ${SIZES[this.sizeBy]}, colour is change against the previous window`]
    if (top && this.total) {
      bits.push(`largest ${top.name} at ${N(top.messages)} messages, ${
        PC(top.messages / this.total * 100)} of ${N(this.total)}`)
    }
    const growingCount = rows.filter((r) => r.pct != null && r.pct > 0).length
    const shrinkingCount = rows.filter((r) => r.pct != null && r.pct < 0).length
    bits.push(`${growingCount} grew, ${shrinkingCount} shrank`)
    return bits.join(", ")
  }

  tipMarkup({ row: r, tone }) {
    const swatch = (t) => `<i style="background: var(--dv-${t})"></i>`
    const rows = [`<div class="row">${swatch(tone)}member messages<b>${N(r.messages)}</b></div>`]
    if (r.prior != null) rows.push(`<div class="row">${swatch("na")}window before<b>${N(r.prior)}</b></div>`)
    const pct = changeOf(r)
    if (pct != null) {
      rows.push(`<div class="row">${swatch(tone)}change<b>${signed(pct)}</b></div>`)
    } else {
      rows.push(`<div class="row">${swatch("na")}change<b>n/a</b></div>`)
      rows.push(`<div class="row row-note"><i></i>base under ${N(this.floor)} messages</div>`)
    }
    if (this.total) rows.push(`<div class="row"><i></i>share of all channels<b>${PC(r.messages / this.total * 100, 2)}</b></div>`)
    return `<div class="t">#${esc(r.name)}</div>${rows.join("")}`
  }

  captionFor({ row: r }) {
    const pct = changeOf(r)
    return `${r.name}, ${N(r.messages)} messages${pct != null ? `, ${signed(pct)}` : ""}`
  }

  displayDefaults() {
    return { labels: true, sizeBy: "messages" }
  }

  displayOptions() {
    return { labels: true, sizeBy: this.tilesValue.some((row) => Number(row.prior) > 0) }
  }

  legendScale() {
    return {
      low: "shrank", high: "grew", steps: TONES.map(toneColor),
      extras: [{ label: `under ${N(this.floor)} before`, color: toneColor("na") }],
      note: `Size: ${SIZES[this.sizeBy]}`
    }
  }

  inspectorLabels() {
    return { point: "Tile", stats: "All tiles" }
  }

  rank(i) {
    return this.items().findIndex((item) => item.i === i) + 1
  }

  pointDetails(i) {
    const r = this.tilesValue[i]
    if (!r) return null

    const tone = this.step(r)
    const color = toneColor(tone)
    const pct = changeOf(r)
    const rank = this.rank(i)
    const value = (label, text, extra = {}) => ({
      label, colorClass: "", color, shape: "box", value: text, change: null, share: null, ...extra
    })
    return {
      title: `#${r.name}`,
      qualifier: TONE_NAMES[tone],
      tags: [],
      note: pct == null ? `Base under ${N(this.floor)} messages` : null,
      total: null,
      values: [
        value("member messages", N(r.messages), {
          change: pct == null ? null : { value: pct, unit: "%" }, comparison: "from the window before"
        }),
        r.prior != null && value("window before", N(r.prior), { color: null, shape: "none" }),
        this.total && value("share of all channels", PC(r.messages / this.total * 100, 2), { color: null, shape: "none" }),
        rank > 0 && value("rank", `${rank} of ${this.items().length}`, { color: null, shape: "none" })
      ].filter(Boolean)
    }
  }

  rangeStats() {
    const rows = this.tilesValue
    const count = (test) => rows.filter((r) => {
      const pct = changeOf(r)
      return pct != null && test(pct)
    }).length
    return {
      summary: [
        { label: "channels", value: N(rows.length) },
        { label: "member messages", value: N(rows.reduce((at, r) => at + (Number(r.messages) || 0), 0)) },
        { label: "grew", value: N(count((pct) => pct >= FLAT_BAND)) },
        { label: "flat", value: N(count((pct) => Math.abs(pct) < FLAT_BAND)) },
        { label: "shrank", value: N(count((pct) => pct <= -FLAT_BAND)) },
        { label: "new", value: N(rows.filter((r) => changeOf(r) == null).length) }
      ]
    }
  }

  tableData() {
    const rows = this.tilesValue
    const share = (r) => (this.total ? r.messages / this.total * 100 : null)
    const columns = [
      { key: "label", label: "Channel", numeric: false },
      { key: "messages", label: "member messages", numeric: true },
      { key: "prior", label: "window before", numeric: true },
      { key: "change", label: "change", numeric: true },
      this.total && { key: "share", label: "share of all channels", numeric: true }
    ].filter(Boolean)
    const order = [...rows.keys()].sort((a, b) => (Number(rows[b][this.sizeBy]) || 0) - (Number(rows[a][this.sizeBy]) || 0))
    const body = order.map((index) => {
      const r = rows[index]
      const pct = changeOf(r)
      const part = share(r)
      return {
        index,
        values: {
          label: r.name, messages: Number(r.messages), prior: r.prior == null ? null : Number(r.prior),
          change: pct, share: part == null ? null : Number(part.toFixed(3))
        },
        display: {
          label: `#${r.name}`, messages: N(r.messages), prior: N(r.prior),
          change: pct == null ? "n/a" : signed(pct), share: PC(part, 2)
        },
        note: pct == null ? "new" : null
      }
    })
    const sum = rows.reduce((at, r) => at + (Number(r.messages) || 0), 0)
    const prior = rows.reduce((at, r) => at + (Number(r.prior) || 0), 0)
    return {
      columns,
      rows: body,
      footer: {
        label: "Total",
        values: { messages: N(sum), prior: N(prior), share: this.total ? PC(sum / this.total * 100, 2) : "" }
      }
    }
  }
}
