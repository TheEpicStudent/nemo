module Fd
  class MemberIdentity < ApplicationRecord
    class NoActorError < ArgumentError; end

    self.table_name = "fd.member_identity"
    self.primary_key = "user_id"

    belongs_to :member, class_name: "Fd::Member", foreign_key: :user_id, inverse_of: :identity

    scope :unpurged, -> { where(purged_at: nil) }

    RefusedError = Class.new do
      def purged? = false

      def email = nil

      def refused? = true
    end

    def self.look_up(user_id, actor:)
      raise NoActorError, "Actor required" if actor.nil?
      return RefusedError.new unless actor.may?("identity.read")

      row = unpurged.find_by(user_id: user_id)
      AccessLog.record!(actor: actor, subject_user_id: user_id, field_class: "identity")
      row
    end

    def refused? = false

    def readonly?
      persisted?
    end

    def purged?
      purged_at.present?
    end
  end
end
