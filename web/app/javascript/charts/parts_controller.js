import { TileChart, clip, esc, fit, N, PC } from "charts/tiles"

const UNIT = "members"

export default class extends TileChart {
  static values = { label: String }

  get boxClass() {
    return "tree parts"
  }

  get defaultHeight() {
    return 200
  }

  get total() {
    return this.tilesValue.reduce((sum, t) => sum + Number(t.value || 0), 0)
  }

  toneIndex(i) {
    const tone = this.tilesValue[i]?.tone
    return tone == null ? i : tone
  }

  keyOf(i) {
    return `p${this.toneIndex(i)}`
  }

  items() {
    const hidden = this.hiddenKeys
    return this.tilesValue
      .map((row, i) => ({ i, row, v: Number(row.value) || 0 }))
      .filter((item) => item.v > 0 && !hidden.has(this.keyOf(item.i)))
      .sort((a, b) => b.v - a.v)
  }

  toneOf(item) {
    return `part-${this.toneIndex(item.i)}`
  }

  seriesOf(item) {
    return this.keyOf(item.i)
  }

  shareOf(row) {
    return PC(Number(row.value) / this.total * 100)
  }

  labelMarkup({ row, x, y, w, h }) {
    const share = this.shareOf(row)
    const maxWidth = w - 10
    const cx = x + w / 2

    let pcSize = Math.max(10, Math.min(16, Math.round(Math.min(w / 4.2, h / 3.6))))
    while (pcSize > 10 && fit(share, pcSize, 500) > maxWidth) pcSize -= 1
    const pcLabel = clip(share, pcSize, maxWidth, 500)

    let nameSize = Math.max(9, Math.round(pcSize * 0.9))
    while (nameSize > 9 && fit(row.label, nameSize) > maxWidth) nameSize -= 1
    let nameLabel = clip(row.label, nameSize, maxWidth)
    const pair = nameSize + pcSize + 4
    if (pair > h - 8) nameLabel = null

    if (nameLabel && pcLabel) {
      const first = y + h / 2 - pair / 2 + nameSize
      return `<text class="t-n" x="${cx.toFixed(1)}" y="${first.toFixed(1)}"
        text-anchor="middle" font-size="${nameSize}"
        style="fill: var(--parts-ink)">${esc(nameLabel)}</text>` +
        `<text class="t-v" x="${cx.toFixed(1)}" y="${
          (first + pcSize + 4).toFixed(1)}" text-anchor="middle" font-size="${pcSize}"
        style="fill: var(--parts-ink)">${esc(pcLabel)}</text>`
    }
    if (pcLabel) {
      return `<text class="t-v" x="${cx.toFixed(1)}" y="${
        (y + h / 2 + pcSize / 3).toFixed(1)}" text-anchor="middle" font-size="${pcSize}"
        style="fill: var(--parts-ink)">${esc(pcLabel)}</text>`
    }
    return ""
  }

  summary() {
    const total = this.total
    const label = this.hasLabelValue && this.labelValue ? this.labelValue : "parts of the whole"
    const bits = [`Treemap of ${label}, area is each part's share of ${N(total)}`]
    this.items().forEach(({ row }) => bits.push(`${row.label} ${N(row.value)}, ${this.shareOf(row)}`))
    return bits.join(". ")
  }

  tipMarkup({ row: r, tone }) {
    return `<div class="t">${esc(r.label)}</div>` +
      `<div class="row"><i class="${tone}"></i>${UNIT}<b>${N(r.value)}</b></div>` +
      `<div class="row"><i></i>share<b>${this.shareOf(r)}</b></div>` +
      `<div class="row"><i></i>of<b>${N(this.total)}</b></div>`
  }

  captionFor({ row: r }) {
    return `${r.label}, ${N(r.value)}, ${this.shareOf(r)}`
  }

  legendEntries() {
    return this.tilesValue
      .map((row, i) => ({ row, i }))
      .filter(({ row }) => Number(row.value) > 0)
      .map(({ row, i }) => ({
        key: this.keyOf(i), label: row.label, colorClass: `part-${this.toneIndex(i)}`, color: null, shape: "box"
      }))
  }

  inspectorLabels() {
    return { point: "Part", stats: "All parts" }
  }

  pointDetails(i) {
    const r = this.tilesValue[i]
    if (!r) return null

    return {
      title: r.label,
      qualifier: null,
      tags: [],
      note: null,
      total: N(this.total),
      values: [{
        label: UNIT, colorClass: `part-${this.toneIndex(i)}`, color: null, shape: "box",
        value: N(r.value), change: null, share: this.shareOf(r)
      }]
    }
  }

  rangeStats() {
    const parts = this.tilesValue.filter((row) => Number(row.value) > 0)
    return {
      summary: [
        { label: UNIT, value: N(this.total) },
        ...parts.map((row) => ({ label: row.label, value: this.shareOf(row) }))
      ]
    }
  }

  tableData() {
    const rows = this.tilesValue
    const total = this.total
    const order = [...rows.keys()]
      .filter((index) => Number(rows[index].value) > 0 && !this.hiddenKeys.has(this.keyOf(index)))
      .sort((a, b) => Number(rows[b].value) - Number(rows[a].value))
    return {
      columns: [
        { key: "label", label: "Part", numeric: false },
        { key: "value", label: UNIT, numeric: true },
        { key: "share", label: "share", numeric: true }
      ],
      rows: order.map((index) => {
        const r = rows[index]
        const share = Number(r.value) / total * 100
        return {
          index,
          values: { label: r.label, value: Number(r.value), share: Number(share.toFixed(3)) },
          display: { label: r.label, value: N(r.value), share: PC(share) },
          note: null
        }
      }),
      footer: { label: "Total", values: { value: N(total), share: PC(100) } }
    }
  }
}
