module Fd
  class LinkVerdict < ApplicationRecord
    self.table_name = "fd.member_link_verdict"

    VERDICTS = {
      "same_person" => "Same person",
      "different_people" => "Different people",
      "household" => "Household",
      "staff_test" => "Staff test"
    }.freeze
    ONE_PERSON = %w[same_person staff_test].freeze

    def self.pair(user_id, other_user_id) = [user_id.to_s, other_user_id.to_s].minmax

    def self.for_pairs(pairs)
      normalized = pairs.map { |user_id, other_user_id| pair(user_id, other_user_id) }.uniq
      return {} if normalized.empty?

      where(a_user_id: normalized.map(&:first), b_user_id: normalized.map(&:last))
        .index_by { |row| [row.a_user_id, row.b_user_id] }.slice(*normalized)
    end

    def self.of(verdicts, user_id, other_user_id) = verdicts[pair(user_id, other_user_id)]

    def label = VERDICTS.fetch(verdict, verdict)

    def one_person? = ONE_PERSON.include?(verdict)

    def verb = one_person? ? "linked" : "unlinked"

    def audit_attributes = { "verdict" => verdict, "decided_by" => decided_by, "note" => note }
  end
end
