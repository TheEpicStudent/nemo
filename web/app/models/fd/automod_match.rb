module Fd
  class AutomodMatch < ApplicationRecord
    self.table_name = "fd.automod_matches"

    belongs_to :automod_word, class_name: "Fd::AutomodWord", foreign_key: :word_id,
      optional: true, inverse_of: :matches

    scope :newest_first, -> { order(at: :desc, id: :desc) }

    def referenced_user_ids
      [user_id].compact
    end
  end
end
