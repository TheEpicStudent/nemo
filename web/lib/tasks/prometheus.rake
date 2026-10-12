namespace :prometheus do
  desc "replace the appointment mirror with what Prometheus holds right now"
  task reconcile: :environment do
    unless Prometheus::Roster.configured?
      puts "prometheus: PROMETHEUS_BASE_URL is not set, so there is nothing to mirror"
      next
    end

    appointment_count = Prometheus::Mirror.reconcile_all
    abort "prometheus: the reconcile did not finish, nothing changed" unless appointment_count

    people = Prometheus::Appointment.distinct.count(:user_id)
    puts "prometheus: #{appointment_count} appointments across #{people} people"
  end
end
