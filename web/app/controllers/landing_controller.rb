class LandingController < ApplicationController
  layout "landing"
  skip_before_action :require_account

  def show
  end
end
