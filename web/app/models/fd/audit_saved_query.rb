module Fd
  class AuditSavedQuery < ApplicationRecord
    self.table_name = "fd.audit_saved_query"

    MAX_NAME_LENGTH = 80
    MAX_QUERY_LENGTH = 500

    validates :name, presence: true, length: { maximum: MAX_NAME_LENGTH }
    validates :query, presence: true, length: { maximum: MAX_QUERY_LENGTH }

    def self.for(account)
      where(owner_user_id: [nil, account&.user_id].uniq)
        .order(Arel.sql("owner_user_id IS NOT NULL"), :name)
    end

    def shared? = owner_user_id.nil?

    def removable_by?(account) = account.present? && created_by == account.user_id

    def params
      { AuditQuery::TERM_KEY => query, "view" => view }.compact
    end
  end
end
