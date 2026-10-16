module Fd
  class MemberTraits
    VALUES_SHOWN = 6

    Value = Struct.new(:key, :text, :note, keyword_init: true)

    PREFIX = "network(set_masklen(%<ip>s, CASE WHEN family(%<ip>s) = 4 THEN 24 ELSE 64 END))".freeze
    TRAITS_SQL = <<~SQL.squish.freeze
      SELECT user_id, kind, value FROM fd.member_trait
      WHERE user_id IN (:ids) AND kind IN ('ip', 'ua_id', 'ja4', 'ja3', 'mailbox')
      ORDER BY last_seen DESC NULLS LAST, value
    SQL
    IP_SQL = format(<<~SQL.squish, prefix: format(PREFIX, ip: "a.ip")).freeze
      SELECT host(a.ip) AS ip, n.network, n.class,
             (SELECT count(*) FROM fd.member_trait t WHERE t.kind = 'ip' AND t.value = host(a.ip)) AS account_count
      FROM unnest(ARRAY[:ips]::inet[]) AS a(ip)
      LEFT JOIN fd.ip_network n ON n.ip_prefix = %<prefix>s
    SQL
    AGENTS_SQL = <<~SQL.squish.freeze
      SELECT id, ua, app, os FROM slack.user_agent WHERE id IN (:ids)
    SQL
    CLIENT_ACCOUNTS_SQL = <<~SQL.squish.freeze
      SELECT agent.label, count(DISTINCT t.user_id) AS account_count
      FROM unnest(ARRAY[:labels]::text[], ARRAY[:ua_ids]::text[]) AS agent(label, ua_id)
      JOIN fd.member_trait t ON t.kind = 'ua_id' AND t.value = agent.ua_id
      GROUP BY agent.label
    SQL
    CHANNELS_SQL = <<~SQL.squish.freeze
      SELECT user_id, channel_id FROM (
        SELECT DISTINCT ON (user_id, channel_id) user_id, channel_id, verb, at
        FROM fd.member_channel_join WHERE user_id IN (:ids)
        ORDER BY user_id, channel_id, at DESC
      ) latest
      WHERE verb = 'joined'
      ORDER BY at DESC
    SQL

    def initialize(user_ids, actor:)
      @ids = user_ids
      @actor = actor
    end

    def identity? = @actor.may?("identity.read")

    def emails(user_id)
      mailbox = traits(user_id, "mailbox").first
      return [] if mailbox.nil?
      return [Value.new(key: mailbox)] unless identity?

      email = MemberIdentity.look_up(user_id, actor: @actor)&.email
      note = mailbox if email.present? && email.downcase != mailbox
      [Value.new(key: mailbox, text: email.presence || mailbox, note: note)]
    end

    def ips(user_id)
      addresses = shown(user_id, "ip")
      return [] if addresses.empty?

      networks = select_all(IP_SQL, ips: addresses.select { |address| address?(address) }.presence || ["0.0.0.0"])
        .index_by { |row| row["ip"] }
      addresses.map do |address|
        network = networks[address] || {}
        kind = network["class"] && AuditSearch::NETWORKS.fetch(network["class"], network["class"])
        note = [network["network"], kind, account_note(network["account_count"].to_i)].compact_blank.join(" · ")
        Value.new(key: address, text: (address if identity?), note: note)
      end
    end

    def clients(user_id)
      agent_ids_by_label = client_agent_ids(user_id)
      return [] if agent_ids_by_label.empty?

      other_labels = other_ids(user_id).flat_map { |other_id| client_agent_ids(other_id).keys }
      labels = shared_first(agent_ids_by_label.keys, other_labels)
      account_counts = client_account_counts(agent_ids_by_label.slice(*labels))
      labels.map { |label| Value.new(key: label, text: label, note: account_note(account_counts[label])) }
    end

    def ja4(user_id)
      shown(user_id, "ja4").map { |value| Value.new(key: value, text: value) }
    end

    def ja3(user_id)
      shown(user_id, "ja3").map { |value| Value.new(key: value, text: value) }
    end

    def channels(user_id)
      @channels ||= select_all(CHANNELS_SQL, ids: @ids).group_by { |row| row["user_id"] }
      @channels.fetch(user_id, []).map { |row| Value.new(key: row["channel_id"], text: row["channel_id"]) }
    end

    def zones(user_id)
      @zones ||= Member.where(user_id: @ids).pluck(:user_id, :tz).to_h
      zone = @zones[user_id]
      zone.present? ? [Value.new(key: zone, text: zone)] : []
    end

    private

    def traits(user_id, kind)
      @traits ||= select_all(TRAITS_SQL, ids: @ids).group_by { |row| [row["user_id"], row["kind"]] }
      @traits.fetch([user_id, kind], []).map { |row| row["value"] }
    end

    def shown(user_id, kind)
      shared_first(traits(user_id, kind), other_ids(user_id).flat_map { |other_id| traits(other_id, kind) })
    end

    def shared_first(values, other_values)
      shared = values & other_values
      (shared + (values - shared)).first(VALUES_SHOWN)
    end

    def other_ids(user_id) = @ids - [user_id]

    def client_agent_ids(user_id)
      @client_agent_ids ||= {}
      @client_agent_ids[user_id] ||= traits(user_id, "ua_id").filter_map do |agent_id|
        agent = agents[agent_id.to_i]
        [agent_label(agent), agent_id] if agent
      end.group_by(&:first).transform_values { |pairs| pairs.map(&:last) }
    end

    def agents
      @agents ||= begin
        agent_ids = @ids.flat_map { |user_id| traits(user_id, "ua_id") }.map(&:to_i).uniq
        agent_ids.empty? ? {} : select_all(AGENTS_SQL, ids: agent_ids).index_by { |row| row["id"].to_i }
      end
    end

    def agent_label(agent)
      [agent["app"], agent["os"]].compact_blank.join(" · ").presence || agent["ua"].to_s.truncate(60)
    end

    def client_account_counts(agent_ids_by_label)
      pairs = agent_ids_by_label.flat_map { |label, agent_ids| agent_ids.map { |agent_id| [label, agent_id] } }
      select_all(CLIENT_ACCOUNTS_SQL, labels: pairs.map(&:first), ua_ids: pairs.map(&:last))
        .to_h { |row| [row["label"], row["account_count"].to_i] }
    end

    def account_note(account_count)
      return nil if account_count.nil?

      account_count = [account_count, 1].max
      "#{account_count} #{'account'.pluralize(account_count)}"
    end

    def address?(value)
      IPAddr.new(value.to_s)
      true
    rescue IPAddr::InvalidAddressError
      false
    end

    def select_all(sql, binds)
      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([sql, binds])).to_a
    end
  end
end
