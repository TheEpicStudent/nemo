module Slack
  class PlainText
    def self.for(blocks, names: {}, channels: {}, usergroups: {})
      new(names, channels, usergroups).text(blocks)
    end

    def initialize(names, channels, usergroups)
      @names = names
      @channels = channels
      @usergroups = usergroups
    end

    def text(blocks)
      Array(blocks).flat_map { |block| block_text(block) }.join(" ").squish
    end

    private

    attr_reader :names, :channels, :usergroups

    def block_text(block)
      case block["type"]
      when "rich_text" then Array(block["elements"]).map { |part| part_text(part) }
      when "section" then [block.dig("text", "text").to_s]
      else []
      end
    end

    def part_text(part)
      return inline_text(part["elements"]) unless part["type"] == "rich_text_list"

      Array(part["elements"]).map { |row| inline_text(row["elements"]) }.join(" ")
    end

    def inline_text(elements)
      Array(elements).map { |node| element_text(node) }.join
    end

    def element_text(node)
      case node["type"]
      when "link" then node["text"].presence || node["url"].to_s
      when "emoji" then emoji_text(node)
      when "user" then prefixed(names[node["user_id"]].presence || node["user_id"], "@")
      when "usergroup" then prefixed(usergroups[node["usergroup_id"]].presence || node["usergroup_id"], "@")
      when "channel" then prefixed(channels[node["channel_id"]].presence || node["channel_id"], "#")
      when "broadcast" then RichText::BROADCASTS.fetch(node["range"], "@#{node['range']}")
      when "message_mention" then node["text"].presence || "a message"
      else node["text"].to_s
      end
    end

    def emoji_text(node)
      UnicodeEmoji.for(node["name"], unicode: node["unicode"], skin_tone: node["skin_tone"]) ||
        ":#{node['name']}:"
    end

    def prefixed(label, mark)
      label = label.to_s
      label.start_with?(mark) ? label : "#{mark}#{label}"
    end
  end
end
