module Fd
  class MemberLinkShadow < ApplicationRecord
    self.table_name = "fd.member_link_shadow"

    VARIANT_NAME = /\A[a-z0-9_]{1,40}\z/

    def self.variant_name(value)
      name = value.to_s
      name.match?(VARIANT_NAME) && name != LinkList::LIVE_VARIANT ? name : nil
    end

    def readonly? = true
  end
end
