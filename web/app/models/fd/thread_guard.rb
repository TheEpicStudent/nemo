module Fd
  class ThreadGuard < ApplicationRecord
    self.table_name = "fd.thread_guards"

    LOCK = "lock".freeze
    DESTROY = "destroy".freeze

    ACTIVE_STATES = %w[warned running].freeze

    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, optional: true,
      inverse_of: false
    has_many :actions, class_name: "Fd::Action", foreign_key: :thread_guard_id,
      inverse_of: :thread_guard, dependent: :nullify

    scope :active, -> { where(state: ACTIVE_STATES) }
    scope :locks, -> { where(kind: LOCK) }
    scope :for_case, ->(case_id) { where(case_id: case_id) }
    scope :newest_first, -> { order(created_at: :desc) }

    def self.selectable_locks(case_ids)
      preferred_case_ids = Array(case_ids).compact
      active.locks
        .order(Arel.sql("case_id IS NULL, created_at DESC"))
        .to_a
        .partition { |guard| preferred_case_ids.include?(guard.case_id) }
        .flatten
    end

    def locking? = kind == LOCK
    def destroying? = kind == DESTROY
    def active? = ACTIVE_STATES.include?(state)
    def failed? = state == "failed"
    def orphaned? = case_id.nil?

    def on_case?(case_ids) = case_id.present? && Array(case_ids).include?(case_id)

    def attach_to!(case_id)
      updated_count = self.class.active.where(id: id, case_id: nil)
        .update_all(case_id: case_id, updated_at: Time.current)
      updated_count.positive? ? reload : nil
    end

    def note? = note_text.present?

    def referenced_user_ids
      [opened_by].compact
    end
  end
end
