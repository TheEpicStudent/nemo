module Settings
  class TokensController < KeysController
    def create
      return redirect_with_alert(turned_off) if api_off?

      app = owned_app(params[:app_id])
      return redirect_with_alert("That app is not yours") if app.nil?
      return redirect_with_alert("Say what the key is for") if params[:name].to_s.strip.empty?

      token, @secret = Api::Token.mint!(app, params[:name], lifetime: params[:lifetime])
      Api::Event.record!("token_minted", actor: member_id, subject: token.display_prefix,
        detail: [app.name, token.name,
          Api::Token::LIFETIME_LABELS.fetch(Api::Token.life_for(params[:lifetime]))].join(", "))

      @token = token
      load_keys
      render "settings/keys/show"
    rescue Api::Token::NotApprovedError
      redirect_with_alert("That app has no approved scope yet")
    rescue Api::Token::TooManyError
      redirect_with_alert("that app already holds #{Api::Setting.value('tokens_per_owner')} keys")
    end

    def rotate
      return redirect_with_alert(turned_off) if api_off?

      token = own_token
      return redirect_with_alert("That key is not yours") if token.nil?

      @secret = token.rotate!(by: member_id)
      @token = token
      load_keys
      render "settings/keys/show"
    end

    def destroy
      token = own_token
      return redirect_with_alert("That key is not yours") if token.nil?

      token.revoke!(by: member_id)
      Api::Event.record!("token_revoked", actor: member_id, subject: token.display_prefix,
        detail: token.name)

      redirect_to settings_keys_path, notice: "Revoked #{token.name}"
    end

    private

    def owned_app(id)
      Api::App.live.find_by(id: id, owner_user_id: member_id)
    end

    def own_token
      Api::Token.live.find_by(id: params[:id], owner_user_id: member_id)
    end

    def redirect_with_alert(message)
      redirect_to settings_keys_path, alert: message
    end
  end
end
