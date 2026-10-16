module Fd
  class AutomodWordsController < BaseController
    permit "app.configure"

    MAX_WORD_LENGTH = 80

    def create
      error = validation_error
      return redirect_with_alert(error) if error

      word = nil
      writing do
        word = AutomodWord.add!(word: word_param, by: current_account.user_id,
          match_mode: match_mode, effect: effect,
          category_key: selected_category, note: params[:note])
        audit(word, "added", after: { "match_mode" => word.match_mode,
          "effect" => word.effect, "category_key" => word.category_key })
      end

      redirect_to fd_configuration_path, notice: "Added to the automod list"
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert("Already on the list")
    end

    def destroy
      word = AutomodWord.active.find_by(id: params[:id])
      return redirect_with_alert("Not on the list") if word.nil?

      writing do
        word.retire!(by: current_account.user_id)
        audit(word, "removed", before: { "active" => true }, after: { "active" => false })
      end

      redirect_to fd_configuration_path, notice: "Removed from the automod list"
    end

    private

    def word_param
      params[:word].to_s.strip
    end

    def match_mode
      requested = params[:match_mode].to_s
      AutomodWord::MATCHES.include?(requested) ? requested : AutomodWord::WORD
    end

    def effect
      requested = params[:effect].to_s
      AutomodWord::SHIPPED_EFFECTS.include?(requested) ? requested : AutomodWord::FLAG
    end

    def selected_category
      requested = params[:category_key].to_s
      requested if InfractionCategory.active_key?(requested)
    end

    def validation_error
      return "no word given" if word_param.blank?
      return "word is over #{MAX_WORD_LENGTH} characters" if word_param.length > MAX_WORD_LENGTH
      return nil unless match_mode == AutomodWord::REGEX

      Regexp.new(word_param)
      nil
    rescue RegexpError => failure
      "that regex does not compile: #{failure.message}"
    end

    def redirect_with_alert(message)
      redirect_to fd_configuration_path, alert: message
    end
  end
end
