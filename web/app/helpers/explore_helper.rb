module ExploreHelper
  EXPAND_ICON = [
    [:polyline, { points: "15 3 21 3 21 9" }],
    [:polyline, { points: "9 21 3 21 3 15" }],
    [:line, { x1: 21, x2: 14, y1: 3, y2: 10 }],
    [:line, { x1: 3, x2: 10, y1: 21, y2: 14 }]
  ].freeze

  def explore_button(key, title: nil, floating: false)
    tag.button(type: "button",
      class: ["btn btn-ghost btn-sm btn-only card-expand", ("card-expand-floating" if floating)].compact.join(" "),
      data: { explore: key, explore_title: title }.compact,
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
