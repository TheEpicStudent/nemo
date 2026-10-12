module Slack
  class EchoCard
    include ActionView::Helpers::TagHelper
    include ActionView::Helpers::OutputSafetyHelper

    BLOCK_TYPES = %w[header context section].freeze

    def self.echo?(blocks)
      Array(blocks).any? { |block| BLOCK_TYPES.include?(block["type"]) }
    end

    def self.render(blocks, **rendering)
      new(**rendering).render(blocks)
    end

    def initialize(names: {}, channels: {}, emoji: {}, user_chip: nil, channel_chip: nil,
                   link_chip: nil)
      @rendering = { names: names, channels: channels, emoji: emoji, user_chip: user_chip,
                     channel_chip: channel_chip, link_chip: link_chip }
    end

    def render(blocks)
      tag.div(safe_join(Array(blocks).filter_map { |block| render_block(block) }), class: "echo-card")
    end

    private

    def render_block(block)
      case block["type"]
      when "header" then head(block.dig("text", "text"))
      when "context" then meta(block["elements"])
      when "section" then mrkdwn(block.dig("text", "text"))
      end
    end

    def head(text)
      return nil if text.blank?

      tag.p(ERB::Util.html_escape(text), class: "echo-head")
    end

    def meta(elements)
      text = Array(elements).filter_map { |element| element["text"] if element["type"] == "mrkdwn" }.join(" ")
      return nil if text.blank?

      tag.div(mrkdwn(text), class: "echo-meta")
    end

    def mrkdwn(text)
      RichText.for({ "blocks" => Mrkdwn.blocks(text.to_s) }, **@rendering)
    end
  end
end
