module Community
  class Access
    def self.superadmin?(staff)
      Fd::Access.manager?(staff)
    end

    EVERY_ACCOUNT = "analytics.workspace.read".freeze

    CAPABILITY = {
      "analytics.member.read" => "member.read",
      "analytics.channel.read" => "channel.read",
      "analytics.channel.share" => "channel.share",
      "analytics.message.show" => "message.show",
      "analytics.message.read" => "message.read",
      "analytics.grant" => "access.grant",
      "ops.engine" => "engine.manage",
      "ops.channel.backfill" => "channel.backfill"
    }.freeze

    def self.capability_for(key)
      CAPABILITY.fetch(key.to_s) { raise Authz::UnknownError, "#{key} is not a permission" }
    end

    def self.allow?(staff, key, record = nil)
      return staff.present? if key.to_s == EVERY_ACCOUNT

      Authz.may?(staff, capability_for(key), record)
    end

    SCOPE_REFUSALS = { author: "Own posts only" }.freeze

    def self.why_not(staff, key, record = nil)
      return nil if allow?(staff, key, record)
      return "No access" if staff.nil?

      capability = capability_for(key)
      return "No access" if !Authz.every_account?(capability) && Authz.effective_capabilities(staff.user_id).empty?
      return Authz.refusal(capability) unless Authz.holds?(staff, capability)

      SCOPE_REFUSALS.fetch(Authz.record_scope(capability), "Granted channels only")
    end

    def self.within_scope?(staff, key, record)
      return true unless key.to_s == "analytics.channel.read"
      return true if record.nil?

      Channels::Audience.may_see?(staff, record)
    end
  end
end
