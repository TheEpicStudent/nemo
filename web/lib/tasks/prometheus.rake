namespace :prometheus do
  desc "replace the appointment mirror with what Prometheus holds right now"
  task reconcile: :environment do
    unless Prometheus::Roster.configured?
      abort "PROMETHEUS_BASE_URL is not set, so there is nothing to reconcile against"
    end

    held = Prometheus::Mirror.reconcile_all
    abort "prometheus: the reconcile did not finish, nothing changed" unless held

    people = Prometheus::Appointment.distinct.count(:user_id)
    puts "prometheus: #{held} appointments across #{people} people"
  end
end
