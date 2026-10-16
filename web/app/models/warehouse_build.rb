module WarehouseBuild
  SOURCE = "dbt".freeze
  FINISHED_AT_TTL = 1.minute
  CACHE_TTL = 2.days

  module_function

  def finished_at
    Rails.cache.fetch("warehouse_build/finished_at", expires_in: FINISHED_AT_TTL) do
      Analytics::FctIngestRun.where(source_key: SOURCE).where.not(finished_at: nil).maximum(:finished_at)&.to_i
    end
  end

  def cached(key, &block)
    Rails.cache.fetch(["warehouse_build", finished_at, key], expires_in: CACHE_TTL, &block)
  end
end
