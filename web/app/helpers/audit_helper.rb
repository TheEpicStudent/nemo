module AuditHelper
  WINDOWS = { "Last hour" => "1h", "Last 24 hours" => "24h", "Last 7 days" => "7d",
              "Last 30 days" => "30d" }.freeze
  ACTOR_TYPES = { "Human" => "human", "nemo" => "nemo", "System" => "nobody" }.freeze
  QUERY_KEYS = [
    ["about", "Actor or target"], %w[actor Actor], %w[by Actor], ["action", "Event type"], ["category", "Event category"],
    ["network", "Network class"], ["country", "Country code"], %w[in Channel], ["is", "Actor type"],
    %w[source Log], ["app", "App ID"], ["session", "Session ID"], ["last", "Time window"],
    %w[after From], %w[before Until], ["show", "Optional events"]
  ].freeze
  IDENTITY_QUERY_KEYS = [["ip", "Source IP"], ["email", "Account email"], ["domain", "Email domain"]].freeze
  NAMED_TOKENS = { "actor" => "actor ", "about" => "about ", "channel" => "in " }.freeze
  ICONS = {
    "search" => ["M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14", "m20 20-3.5-3.5"],
    "x" => ["M18 6 6 18", "M6 6l12 12"],
    "copy" => ["M8 8h12v12H8z", "M16 8V4H4v12h4"],
    "bookmark" => ["M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"]
  }.freeze
  FIRST_DAY = Fd::AuditQuery::FIRST_DAY
  CHEVRON = "m6 9 6 6 6-6".freeze

  def audit_stamp(time)
    local = time.in_time_zone
    tag.time(datetime: local.iso8601, title: time.utc.strftime("%-d %b %Y %H:%M:%S UTC")) do
      safe_join([local.strftime("%-d %b"), " ", tag.span(local.strftime("%H:%M"), class: "audit-clock")])
    end
  end

  def audit_group_value(group, group_row)
    case group
    when "actor" then member_face(group_row.key)
    when "action" then tag.span(Fd::AuditCatalogue.action_label(group_row.key), class: "audit-verb")
    when "address" then tag.span(group_row.key, class: "mono")
    when "channel" then audit_channel(group_row.key)
    when "app" then group_row.name.presence || tag.span(group_row.key, class: "mono")
    when "country" then tag.span(group_row.key, class: "mono")
    end
  end

  def audit_pivots(query, row)
    query.pivots(row).reject { |pivot| pivot.kind == "channel" && !channels.named?(row.channel) }
  end

  PIVOT_ICON = "M3 4h18l-7 8.5V18l-4 2v-7.5z".freeze

  def pivot_icon
    tag.svg(tag.path(d: PIVOT_ICON), width: 13, height: 13, viewBox: "0 0 24 24", fill: "none",
      stroke: "currentColor", "stroke-width": 2, "stroke-linejoin": "round", "aria-hidden": true)
  end

  def audit_filter_trigger(key, value)
    safe_join([
      tag.span(key, class: "filter-key"),
      (tag.span(value, class: "filter-val") if value.present?),
      tag.svg(tag.path(d: CHEVRON), width: 11, height: 11, viewBox: "0 0 24 24", fill: "none",
        stroke: "currentColor", "stroke-width": 2.5, "aria-hidden": true)
    ].compact)
  end

  def audit_icon(name, size: 15)
    tag.svg(width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": true) do
      safe_join(ICONS.fetch(name).map { |path| tag.path(d: path) })
    end
  end

  def audit_token_parts(term)
    return [nil, term.value] if term.kind == "text"

    prefix = NAMED_TOKENS[term.kind]
    [term.kind == "channel" ? "in" : term.kind, prefix ? term.label.to_s.delete_prefix(prefix) : term.value]
  end

  def audit_query_keys(query)
    query.identity? ? QUERY_KEYS + IDENTITY_QUERY_KEYS : QUERY_KEYS
  end

  def audit_query_choices
    {
      "category" => Fd::AuditCatalogue::CATEGORIES.to_a,
      "action" => Fd::AuditCatalogue::ACTIONS.map { |key, action| [key, action["label"]] },
      "network" => Fd::AuditSearch::NETWORKS.to_a,
      "is" => ACTOR_TYPES.map { |label, key| [key, label] },
      "by" => [%w[me You]],
      "last" => WINDOWS.map { |label, key| [key, label] },
      "source" => Fd::AuditQuery::SOURCES.map { |key| [key, FdHelper::AUDIT_SOURCE.fetch(key, key)] },
      "show" => [["high_volume", "Previews, downloads and list edits"], ["access_logs", "Access log sign-ins"]]
    }
  end

  def audit_count(count)
    tag.span(number_with_delimiter(count.to_i), class: "menu-count") unless count.nil?
  end

  def audit_category_counts(action_counts)
    return nil if action_counts.nil?

    action_counts.each_with_object(Hash.new(0)) do |(action, count), category_counts|
      category = Fd::AuditCatalogue::ACTIONS.dig(action, "category")
      category_counts[category] += count if category
    end
  end

  def audit_ordered(keys, counts)
    return keys if counts.nil?

    keys.sort_by { |key| -counts.fetch(key, 0) }
  end

  QUERY_PEOPLE = 8

  def audit_query_people(rows)
    member_ids = rows.flat_map { |row| [row.actor_id, row.subject_id] }.compact.uniq
      .grep(Fd::AuditQuery::MEMBER_ID).first(QUERY_PEOPLE)
    member_ids.map do |user_id|
      handle = names.member(user_id)&.handle
      [handle.present? ? "@#{handle}" : user_id, names[user_id]]
    end
  end
end
