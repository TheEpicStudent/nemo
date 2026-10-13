module LinkHelper
  BAND_LABELS = { "certain" => "Certain", "strong" => "Strong", "weak" => "Weak" }.freeze
  BAND_TONES = { "certain" => "state-crit", "strong" => "state-warn" }.freeze
  SENSITIVE_SIGNALS = (
    Fd::MemberLink::SIGNALS.fetch("network_signals", {}).keys +
    Fd::MemberLink::SIGNALS.fetch("identity_signals", {}).keys +
    %w[created_same_address after_ban_address]
  ).freeze
  SIGNAL_VALUE = 40
  LANE_WIDTH = 1000
  LANE_LEFT = 120
  LANE_RIGHT = 16
  LANE_ROWS = [40, 92].freeze
  LANE_TICKS = 7
  LINK_LABELS = { "staff_test" => "staff test" }.freeze

  def link_label_text(label) = LINK_LABELS.fetch(label, label.to_s.tr("_", " "))

  def link_band_state(score, with_score: true)
    band = Fd::LinkList.band(score)
    parts = [BAND_LABELS.fetch(band)]
    parts << tag.span(number_with_precision(score, precision: 1), class: "px-obj") if with_score
    tag.span(safe_join(parts, " "), class: ["state", BAND_TONES[band]].compact.join(" "))
  end

  def link_signal_hidden?(name) = SENSITIVE_SIGNALS.include?(name) && !current_account&.may?("identity.read")

  def link_signal_value(entry)
    return locked_note("Hidden") if link_signal_hidden?(entry["name"])

    tag.span(entry["value"].to_s.truncate(SIGNAL_VALUE), class: "mono", title: entry["value"].to_s)
  end

  def link_signal_lines(evidence, limit: 2)
    safe_join(evidence.first(limit).map do |entry|
      parts = [entry["label"]]
      parts += [" ", link_signal_value(entry)] if entry["value"].present?
      tag.div(safe_join(parts), class: "sub2")
    end)
  end

  def link_pair(a, b)
    tag.span(class: "px-where") do
      safe_join([member_face(a), tag.span(link_glyph, class: "sub2"), member_face(b)])
    end
  end

  def link_glyph
    tag.svg(width: 13, height: 13, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
      "stroke-linecap": "round", "aria-hidden": true) do
      safe_join([tag.path(d: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"),
                 tag.path(d: "M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7")])
    end
  end

  def link_compare_path(a, b, back: request.fullpath, variant: nil)
    fd_link_compare_path({ a: a, b: b, back: back, variant: variant }.compact)
  end

  def link_verdict_state(verdict_key, title: nil)
    return "" if verdict_key.blank?

    tone = Fd::LinkVerdict::ONE_PERSON.include?(verdict_key) ? "state-crit" : "state-good"
    tag.span(Fd::LinkVerdict::VERDICTS.fetch(verdict_key, verdict_key), class: "state #{tone}", title: title)
  end

  def link_review_button(a, b, verdict_key, back: request.fullpath, variant: nil)
    label = if may_judge?
      verdict_key ? "Change" : "Review"
    else
      "Compare"
    end
    link_to label, link_compare_path(a, b, back: back, variant: variant), class: "btn btn-sm", data: { turbo_frame: "_top" }
  end

  def link_match_cell(attribute)
    match = attribute.match
    return "" if match.nil?
    return tag.span(compare_icon("x"), class: "cmp-no", title: "No match") if match[:shared].zero?
    return tag.span(compare_icon("check"), class: "cmp-yes", title: "Match") if match[:shared] == match[:of]

    tag.span("#{match[:shared]} of #{match[:of]}", class: "cmp-part", title: "Shared values")
  end

  COMPARE_ICONS = { "x" => ["M18 6 6 18", "M6 6l12 12"], "check" => ["M20 6 9 17l-5-5"] }.freeze

  def compare_icon(name)
    tag.svg(width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2.4,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": true) do
      safe_join(COMPARE_ICONS.fetch(name).map { |path| tag.path(d: path) })
    end
  end

  def compare_row(label, a_cell, match, b_cell)
    tag.div(class: "cmp-row") do
      safe_join([tag.div(label, class: "cmp-key"), tag.div(a_cell, class: "cmp-side"),
                 tag.div(match, class: "cmp-match"), tag.div(b_cell, class: "cmp-side")])
    end
  end

  def link_attribute_values(attribute, values, theirs)
    return tag.span("n/a", class: "cmp-none") if values.empty?

    shared = theirs.map(&:key)
    safe_join(values.map do |value|
      tag.div(class: "cmp-line") do
        safe_join([link_attribute_text(attribute, value, shared.include?(value.key)),
                   (tag.span(value.note, class: "cmp-note") if value.note.present?)].compact)
      end
    end)
  end

  def link_attribute_text(attribute, value, hit)
    body = if value.text.nil?
      locked_note("Hidden")
    elsif attribute.key == "channels"
      channel_label(value.key)
    elsif %w[ip ja4 ja3 email].include?(attribute.key)
      tag.span(value.text, class: "mono")
    else
      value.text
    end
    tag.span(body, class: ["cmp-value", ("is-shared" if hit)].compact.join(" "),
      data: { v: Digest::SHA256.hexdigest("#{attribute.key}:#{value.key}")[0, 16] })
  end

  def link_duration(seconds)
    seconds = seconds.to_f.abs
    return "#{(seconds / 60).round} min" if seconds < 1.hour
    return "#{(seconds / 3600).round} h" if seconds < 2.days

    "#{(seconds / 86_400).round} d"
  end

  def compare_event(compare, event)
    text = case event.kind
    when "joined"
      gap = compare.returned_after_ban(event.user_id)
      safe_join(["Joined", (tag.span(" #{link_duration(gap)} after the ban", class: "cmp-event-alert") if gap)].compact)
    when "deactivated"
      by = compare.account(event.user_id).deactivated_by
      tag.span(safe_join(["Deactivated", (safe_join([" by ", person_label(by)]) if by)].compact), class: "cmp-event-alert")
    else
      compare_sign_in(compare, event)
    end
    tag.div(text, class: ["cmp-event", "is-#{event.kind.tr('_', '-')}", ("is-shared" if event.shared)].compact.join(" "))
  end

  def compare_sign_in(compare, event)
    network = event.network && Fd::AuditSearch::NETWORKS.fetch(event.network, event.network)
    address = if compare.identity?
      tag.span(event.ip, class: "mono")
    elsif event.ip
      locked_note("Hidden")
    end
    parts = [event.count > 1 ? "Signed in #{event.count} times" : "Signed in"]
    parts += [" from ", address] if address
    parts << tag.span(" #{network}", class: "cmp-note") if network
    parts << tag.span(" same IP within 1 h", class: "cmp-event-shared") if event.shared
    safe_join(parts)
  end
end
