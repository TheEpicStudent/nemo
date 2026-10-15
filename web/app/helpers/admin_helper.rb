module AdminHelper
  def role_capability_switch(role, key, override)
    allowed = override ? override.allowed : Authz.baseline(role).include?(key)
    label = "#{Authz.role_label(role)}: #{key}"
    disabled_reason = Authz.locked?(key) ? "#{key} is FD only, it cannot be moved" : why_not("access.grant")
    if disabled_reason
      return tag.span(class: "switch", role: "switch", tabindex: "0",
        aria: { checked: allowed.to_s, disabled: "true", label: label, description: disabled_reason })
    end

    button_to allowed ? "On" : "Off",
      fd_role_permission_path(role: role, key: key, allowed: allowed ? "0" : "1"),
      method: :patch, class: "switch", form: { class: "contents" },
      role: "switch", aria: { checked: allowed.to_s, label: label }
  end

  def role_standing(user_id, roles: nil, extras: nil)
    roles ||= Authz.effective_roles(user_id)
    extras ||= Authz::Grant.live.for_person(user_id).capabilities.where(effect: "allow").count
    text = roles.any? ? roles.map { |role| Authz.role_label(role) }.to_sentence : "No role"

    parts = [tag.span(text, class: roles.any? ? "" : "sub2")]
    if extras.positive?
      parts << tag.span("with #{pluralize(extras, 'extra scope')}", class: "chip chip-good")
    end
    safe_join(parts, " ")
  end

  ROLE_NOTES = {
    "community_manager" => "Everything, including handing access out",
    "firefighter" => "Works cases",
    "promethean" => "Reads the channels you name to them",
    "gardener" => "Reads one shared set of channels"
  }.freeze

  def role_note(name)
    ROLE_NOTES.fetch(name.to_s, "")
  end

  AUDIENCE_TONE = { "public" => "chip chip-warn", "everyone" => "chip chip-warn" }.freeze

  AUDIENCE_NOTE = {
    "granted" => "only the people you name",
    "private" => "only the people you name",
    "shared" => "only the people you name",
    "public" => "anyone signed in, no grant needed",
    "everyone" => "anyone signed in, no grant needed"
  }.freeze

  FACE_LIMIT = 4

  def audience_chip(kind)
    tag.span(kind.to_s.upcase_first, class: AUDIENCE_TONE.fetch(kind, "chip chip-off"))
  end

  def grant_faces(grants, kind)
    return tag.span("Anyone signed in", class: "sub") if
      Channels::Audience::OPEN.include?(kind)

    people = grants.select { |grant| grant.user_id.present? }
    roles = grants.filter_map { |grant| grant.role.presence }.uniq
    return tag.span("Nobody", class: "sub") if people.empty? && roles.empty?

    safe_join([role_chips(roles), face_stack(people)].compact, " ")
  end

  def role_label_text(role)
    Authz.role_names.include?(role.to_s) ? Authz.role_label(role).downcase : role.to_s
  end

  def role_chips(roles)
    return nil if roles.empty?

    safe_join(roles.map { |role| tag.span("#{role_label_text(role).upcase_first} set", class: "chip") }, " ")
  end

  def face_stack(people)
    return nil if people.empty?

    visible = people.first(FACE_LIMIT)
    stack = tag.span(class: "avatar-stack") do
      safe_join(visible.map { |grant| avatar(grant.user_id) })
    end
    return stack if people.size <= FACE_LIMIT

    stack + tag.span("+#{people.size - FACE_LIMIT}", class: "chip chip-off")
  end

  def channel_cell(channel_id, channel)
    marks = [tag.span(channel_id)]
    marks << tag.span("· private") if channel&.visibility == "private"
    marks << tag.span("· archived") if channel&.archived

    tag.span(class: "two-line") do
      tag.b("##{channel&.name.presence || channel_id}") +
        tag.span(safe_join(marks, " "), class: "mono")
    end
  end

  def acted_bar(count, busiest)
    return tag.span("Never", class: "sub") if count.to_i.zero?

    width = busiest.to_i.positive? ? (count * 100.0 / busiest).round : 0
    tag.span(class: "inbar") do
      tag.span(tag.i(nil, style: "width: #{width}%")) + tag.span(count)
    end
  end

  JOIN_MODES = {
    Fd::AppSetting::ON => "All public",
    Fd::AppSetting::GUARDED => "Guarded only",
    Fd::AppSetting::OFF => "None"
  }.freeze

  JOIN_NOTES = {
    Fd::AppSetting::ON => "Every public channel",
    Fd::AppSetting::GUARDED => "Guarded and configured channels",
    Fd::AppSetting::OFF => "Configured channels only"
  }.freeze

  def admin_join_mode_switch(mode)
    form_with(url: admin_settings_join_mode_path, method: :post, class: "segmented") do
      safe_join(JOIN_MODES.map { |key, label|
        button_tag(label, name: "mode", value: key, "aria-pressed": (key == mode).to_s)
      })
    end
  end
end
