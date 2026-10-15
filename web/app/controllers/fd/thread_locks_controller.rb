module Fd
  class ThreadLocksController < BaseController
    permit "thread.guard"

    def update
      lock = live_lock
      return redirect_to(return_path, alert: "Lock already ended") if lock.nil?

      ends, error = Durations.read(params[:extend_by], params[:expires_on], params[:expires_time],
        from: lock.expires_at)
      return redirect_to(return_path, alert: error || "Select how long to extend") if ends.nil?

      previous_end = lock.expires_at
      writing do
        lock.update!(expires_at: ends, updated_at: Time.current)
        audit(lock, "extended", before: { "expires_at" => previous_end&.iso8601 },
          after: { "expires_at" => ends.iso8601 })
      end

      redirect_to return_path, notice: "Lock extended · ends #{ShortDate.ending(ends)}"
    end

    def destroy
      lock = live_lock
      return redirect_to(return_path, alert: "Lock already ended") if lock.nil?

      writing do
        lock.update!(state: "done", finished_at: Time.current, updated_at: Time.current)
        audit(lock, "lifted", before: { "state" => "running" }, after: { "state" => "done" })
      end

      redirect_to return_path, notice: "Thread unlocked"
    end

    private

    def live_lock = ThreadGuard.still_on.locks.find_by(id: params[:id])

    def return_path = fd_case_path(params[:case_id])
  end
end
