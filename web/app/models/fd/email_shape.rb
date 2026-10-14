module Fd
  module EmailShape
    ADDRESS_LETTERS = /\A[a-z]+\z/i
    LETTER = /[a-z]/i
    DELIMITERS = /[\s":]+/
    WHITESPACE = /\s/

    module_function

    def full?(text)
      value = text.to_s
      return false if value.match?(WHITESPACE) || value.count("@") != 1

      local, domain = value.split("@", 2)
      !local.empty? && dotted_inside?(domain)
    end

    def address?(text)
      return false unless full?(text)

      before, _dot, last = text.to_s.split("@", 2).last.rpartition(".")
      !before.empty? && last.match?(ADDRESS_LETTERS)
    end

    def within?(text)
      text.to_s.split(DELIMITERS).any? { |piece| piece_holds_address?(piece) }
    end

    def piece_holds_address?(piece)
      piece.split("@", -1).each_cons(2).any? { |local, domain| !local.empty? && dot_then_letter?(domain) }
    end

    def dotted_inside?(domain)
      domain.length >= 3 && domain[1..-2].include?(".")
    end

    def dot_then_letter?(domain)
      domain.each_char.with_index.any? do |char, at|
        char == "." && at.positive? && domain[at + 1].to_s.match?(LETTER)
      end
    end
  end
end
