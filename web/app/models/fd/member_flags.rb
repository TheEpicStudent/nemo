module Fd
  class MemberFlags
    Flag = CaseFlags::Flag

    WINDOW = 12.months
    NOTE_EXCERPT_LENGTH = 90

    def self.for_member(record, names: Names.none)
      new(record, names).flags
    end

    def initialize(record, names)
      @record = record
      @names = names
    end

    def flags
      [record_flag, standing_note_flag].compact
    end

    private

    def record_flag
      recent = @record.subject_cases.select { |kase| kase.opened_at >= WINDOW.ago }
      return nil if recent.empty?

      actioned_count = recent.count { |kase| actioned_in?(kase) }
      Flag.new(tone: actioned_count.positive? ? "crit" : "mid",
        headline: "#{pluralised(recent.size)} in the last year, #{action_outcome(actioned_count)}.",
        detail: standing_detail)
    end

    def pluralised(count)
      count == 1 ? "One case" : "#{count} cases"
    end

    def action_outcome(actioned_count)
      return "none ended in action" if actioned_count.zero?
      return "one ended in action" if actioned_count == 1

      "#{actioned_count} ended in action"
    end

    def standing_detail
      live = @record.actions.reject { |a| a.reversed? || a.expired? }
        .max_by(&:performed_at)
      return nil if live.nil?

      label = ACTION_WORDS.fetch(live.type_key) { live.type_key.tr("_", " ") }
      on = live.performed_at.strftime("%-d %b")
      return "The #{label} from #{on} runs until #{live.expires_at.strftime('%-d %b')}." if
        live.expires?

      "The #{label} from #{on} is a prior on their record."
    end

    ACTION_WORDS = {
      "warning" => "warning", "shush" => "shush", "temp_ban" => "temporary ban",
      "indef_ban" => "indefinite ban", "perma_ban" => "permanent ban",
      "channel_ban" => "channel ban", "locked_thread" => "thread lock", "dm" => "DM"
    }.freeze

    def actioned_in?(kase)
      @record.actions.any? { |a| a.case_id == kase.id && !a.reversed? }
    end

    def standing_note_flag
      note = @record.notes.first
      return nil if note.nil?

      Flag.new(tone: "mid", headline: "A standing note is on them.",
        detail: "\u201C#{note.body.to_s.truncate(NOTE_EXCERPT_LENGTH)}\u201D " \
                "#{@names[note.author]}, #{note.created_at.strftime('%-d %b')}.")
    end
  end
end
