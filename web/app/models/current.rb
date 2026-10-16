class Current < ActiveSupport::CurrentAttributes
  attribute :role_overrides, :flag_states, :engine_settings, :effective_capabilities, :effective_roles, :categories

  def role_permissions
    self.role_overrides ||= Authz::Override.pluck(:role, :capability, :allowed)
      .each_with_object({}) { |(role, key, allowed), map| map[[role, key]] = allowed }
  end

  def forget_roles
    self.role_overrides = nil
    self.effective_capabilities = nil
    self.effective_roles = nil
  end

  def flags
    self.flag_states ||= Fd::Flag.states
  end

  def forget_flags
    self.flag_states = nil
  end

  def forget_engine_settings
    self.engine_settings = nil
  end
end
