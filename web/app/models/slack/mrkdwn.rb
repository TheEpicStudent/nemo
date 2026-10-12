module Slack
  class Mrkdwn
    FENCE = /```\n?(.*?)```/m
    QUOTE = /\A(?:>|&gt;)\s?/
    ENTITIES = { "&amp;" => "&", "&lt;" => "<", "&gt;" => ">" }.freeze
    ENTITY = /&(?:amp|lt|gt);/

    TOKEN = %r{
      (?<code>`(?<code_in>[^`\n]+)`)
      | (?<user><@(?<user_id>[UW][A-Z0-9]{2,})(?:\|[^>]*)?>)
      | (?<channel><\#(?<channel_id>C[A-Z0-9]{2,})(?:\|(?<channel_name>[^>]*))?>)
      | (?<link><(?<url>https?://[^|>\s]+)(?:\|(?<label>[^>]*))?>)
      | (?<bare>https?://[^\s<>]+)
      | (?<emoji>:(?<emoji_name>[a-z0-9][a-z0-9_+'\-]*):)
      | (?<bold>\*(?<bold_in>[^*\n]*\S)\*)
      | (?<italic>_(?<italic_in>[^_\n]*\S)_)
      | (?<strike>~(?<strike_in>[^~\n]*\S)~)
    }x

    def self.blocks(text)
      new(text).blocks
    end

    def initialize(text)
      @text = text.to_s
    end

    def blocks
      parts = segments.filter_map { |raw_segment| segment(raw_segment) }
      parts.any? ? [{ "type" => "rich_text", "elements" => parts }] : []
    end

    private

    def segment(raw_segment)
      case raw_segment[:kind]
      when :pre
        { "type" => "rich_text_preformatted",
          "elements" => [{ "type" => "text", "text" => unescape(raw_segment[:text]) }] }
      when :quote
        { "type" => "rich_text_quote", "elements" => inline(raw_segment[:text]) }
      else
        { "type" => "rich_text_section", "elements" => inline(raw_segment[:text]) }
      end
    end

    def segments
      result = []
      at = 0
      @text.scan(FENCE) do
        match = Regexp.last_match
        result.concat(plain_segments(@text[at...match.begin(0)]))
        result << { kind: :pre, text: match[1].sub(/\n\z/, "") }
        at = match.end(0)
      end
      result.concat(plain_segments(@text[at..].to_s))
      result
    end

    def plain_segments(text)
      return [] if text.to_s.strip.empty?

      text.split("\n", -1)
        .chunk_while { |line, next_line| quoted?(line) == quoted?(next_line) }
        .filter_map { |run| run_segment(run) }
    end

    def run_segment(run)
      quoting = quoted?(run.first)
      body = run.map { |line| quoting ? line.sub(QUOTE, "") : line }.join("\n")
      return nil if body.strip.empty?

      { kind: quoting ? :quote : :section, text: body }
    end

    def quoted?(line)
      line.match?(QUOTE)
    end

    def inline(text, style = {})
      out = []
      at = 0
      while (match = TOKEN.match(text, at))
        before = text[at...match.begin(0)]
        out << text_part(before, style) unless before.empty?
        out.concat(parts_for(match, style))
        at = match.end(0)
      end
      remainder = text[at..].to_s
      out << text_part(remainder, style) unless remainder.empty?
      out
    end

    def parts_for(match, style)
      return [text_part(match[:code_in], style.merge("code" => true))] if match[:code]
      return [{ "type" => "user", "user_id" => match[:user_id] }] if match[:user]
      return [{ "type" => "channel", "channel_id" => match[:channel_id] }] if match[:channel]
      return [link_part(match[:url], match[:label])] if match[:link]
      return [link_part(match[:bare], nil)] if match[:bare]
      return [{ "type" => "emoji", "name" => match[:emoji_name] }] if match[:emoji]
      return inline(match[:bold_in], style.merge("bold" => true)) if match[:bold]
      return inline(match[:italic_in], style.merge("italic" => true)) if match[:italic]

      inline(match[:strike_in], style.merge("strike" => true))
    end

    def text_part(text, style)
      element = { "type" => "text", "text" => unescape(text) }
      element["style"] = style if style.any?
      element
    end

    def link_part(url, label)
      element = { "type" => "link", "url" => unescape(url.to_s) }
      display_text = unescape(label.to_s)
      element["text"] = display_text if display_text.present? && display_text != element["url"]
      element
    end

    def unescape(text)
      text.to_s.gsub(ENTITY) { |entity| ENTITIES[entity] }
    end
  end
end
