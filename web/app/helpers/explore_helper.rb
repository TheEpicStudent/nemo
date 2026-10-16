module ExploreHelper
  EXPAND_ICON = [
    [:polyline, { points: "15 3 21 3 21 9" }],
    [:polyline, { points: "9 21 3 21 3 15" }],
    [:line, { x1: 21, x2: 14, y1: 3, y2: 10 }],
    [:line, { x1: 3, x2: 10, y1: 21, y2: 14 }]
  ].freeze

  DISPLAY_SETTINGS = [
    ["Chart", [
      { key: "kind", label: "Type", choices: [["bars", "Bars"], ["line", "Line"]] },
      { key: "stacked", label: "Stacked" }
    ]],
    ["X axis", [
      { key: "xScale", label: "Scale", choices: [["linear", "Linear"], ["log", "Log"]] }
    ]],
    ["Y axis", [
      { key: "yScale", label: "Scale", choices: [["linear", "Linear"], ["log", "Log"]] },
      { key: "zero", label: "Start at zero" },
      { key: "fit", label: "Fit to data" }
    ]],
    ["Numbers", [
      { key: "format", label: "Format", choices: [["full", "1,204", "Full"], ["compact", "1.2k", "Compact"]] }
    ]],
    ["Tiles", [
      { key: "sizeBy", label: "Size by", choices: [["messages", "This window"], ["prior", "Prior period"]] }
    ]],
    ["Show", [
      { key: "grid", label: "Gridlines", shortcut: "G" },
      { key: "notes", label: "Annotations", shortcut: "A" },
      { key: "labels", label: "Labels" },
      { key: "overview", label: "Overview", shortcut: "N" }
    ]]
  ].freeze

  def explore_button(key, title: nil, floating: false, range: nil)
    range = { href: range } if range.is_a?(String)
    tag.button(type: "button",
      class: ["btn btn-ghost btn-sm btn-only card-expand", ("card-expand-floating" if floating)].compact.join(" "),
      data: { explore: key, explore_title: title, explore_range: range&.dig(:href),
              explore_range_keys: range&.dig(:keys) }.compact,
      aria: { label: title ? "Expand #{title}" : "Expand chart", keyshortcuts: "v" }) do
      explore_icon
    end
  end

  def explore_icon
    tag.svg(width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true") do
      EXPAND_ICON.each { |name, attrs| concat tag.public_send(name, **attrs) }
    end
  end
end
