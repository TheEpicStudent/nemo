module Fd
  class Names
    PERSON = /\A[UW][A-Z0-9]+\z/

    def self.for(user_ids)
      ids = Array(user_ids).flatten.compact.uniq.grep(PERSON)
      return none if ids.empty?

      new(members: Member.where(user_id: ids).index_by(&:user_id))
    end

    def self.none = new

    def initialize(members: {})
      @members = members
      @display_cache = {}
    end

    def [](user_id)
      return "n/a" if user_id.blank?

      @display_cache[user_id] ||= label_for(user_id) ||
        (user_id.match?(PERSON) ? "@#{user_id}" : user_id)
    end

    def unknown?(user_id)
      user_id.present? && self[user_id] == "@#{user_id}"
    end

    def initial(user_id)
      label = self[user_id].sub(/\A@/, "").strip
      label.present? ? label[0].upcase : "?"
    end

    def member(user_id)
      @members[user_id]
    end

    def known?(user_id)
      @members.key?(user_id)
    end

    def list(user_ids)
      Array(user_ids).map { |id| self[id] }.to_sentence
    end

    private

    def label_for(user_id)
      @members[user_id]&.name
    end
  end
end
