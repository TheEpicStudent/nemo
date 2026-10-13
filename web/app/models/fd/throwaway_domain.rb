module Fd
  class ThrowawayDomain < ApplicationRecord
    self.table_name = "fd.throwaway_domain"
    self.primary_key = "domain"

    def self.domain_of(email)
      text = email.to_s.strip.downcase
      text.include?("@") ? text.split("@", 2).last : nil
    end

    def self.listed?(email)
      domain = domain_of(email)
      domain.present? && exists?(domain: domain)
    end

    def readonly? = true
  end
end
