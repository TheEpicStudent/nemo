module Fd
  module RosterSql
    IDENTITY_READ = "identity.read".freeze

    AGGREGATES = <<~SQL
      conduct AS (
        SELECT p.user_id,
               count(DISTINCT p.case_id) AS cases,
               count(*) FILTER (WHERE p.role = 'subject') AS subject_of,
               count(*) FILTER (WHERE p.role <> 'subject') AS logged_in,
               count(*) FILTER (WHERE p.role = 'subject' AND c.resolved_at IS NULL) AS open_cases,
               max(c.opened_at) AS last_case_at
        FROM fd.case_participants p
        JOIN fd.cases c ON c.id = p.case_id
        WHERE (:category = 'any' OR c.category_key = :category)
        GROUP BY p.user_id
      ),
      acted AS (
        SELECT target_user_id AS user_id,
               count(*) AS actions,
               count(DISTINCT case_id) FILTER (
                 WHERE reversed_at IS NULL AND performed_at >= :prior_since
               ) AS priors
        FROM fd.actions
        WHERE target_user_id IS NOT NULL
        GROUP BY target_user_id
      ),
      held AS (
        SELECT subject_id AS user_id, count(*) AS in_force
        FROM fd.member_guards
        WHERE state IN ('live', 'lifting')
        GROUP BY subject_id
      ),
      noted AS (
        SELECT subject_user_id AS user_id, count(*) AS notes
        FROM fd.notes
        WHERE case_id IS NULL AND subject_user_id IS NOT NULL AND deleted_at IS NULL
        GROUP BY subject_user_id
      ),
      linked AS (
        SELECT user_id, count(*) AS links
        FROM fd.member_link_side
        WHERE score >= :strong
        GROUP BY user_id
      ),
      touched AS (
        SELECT p.user_id FROM fd.case_participants p
        JOIN fd.cases c ON c.id = p.case_id
        WHERE (:category = 'any' OR c.category_key = :category)
        UNION SELECT target_user_id FROM fd.actions WHERE target_user_id IS NOT NULL
        UNION SELECT subject_id FROM fd.member_guards WHERE state IN ('live', 'lifting')
        UNION SELECT subject_user_id FROM fd.notes
        WHERE case_id IS NULL AND subject_user_id IS NOT NULL AND deleted_at IS NULL
      ),
      people AS (PEOPLE_FROM),
      roster AS (
        SELECT people.user_id,
               coalesce(conduct.cases, 0) AS cases,
               coalesce(conduct.subject_of, 0) AS subject_of,
               coalesce(conduct.logged_in, 0) AS logged_in,
               coalesce(conduct.open_cases, 0) AS open_cases,
               conduct.last_case_at,
               coalesce(acted.actions, 0) AS actions,
               coalesce(held.in_force, 0) AS in_force,
               coalesce(acted.priors, 0) AS priors,
               coalesce(noted.notes, 0) AS notes,
               coalesce(linked.links, 0) AS links,
               coalesce(m.is_deleted, false) AS deactivated,
               m.display_name, m.handle
        FROM people
        LEFT JOIN conduct ON conduct.user_id = people.user_id
        LEFT JOIN acted ON acted.user_id = people.user_id
        LEFT JOIN held ON held.user_id = people.user_id
        LEFT JOIN noted ON noted.user_id = people.user_id
        LEFT JOIN linked ON linked.user_id = people.user_id
        LEFT JOIN fd.member m ON m.user_id = people.user_id
        CONTEXT_JOIN
      )
    SQL

    EVERYONE = <<~SQL.squish.freeze
      SELECT user_id FROM fd.member WHERE is_deleted = false AND is_bot = false
      UNION ALL
      SELECT user_id FROM touched WHERE NOT EXISTS (
        SELECT 1 FROM fd.member live
        WHERE live.user_id = touched.user_id AND live.is_deleted = false AND live.is_bot = false
      )
    SQL

    TOUCHED = "SELECT user_id FROM touched".freeze
    DEACTIVATED = "SELECT user_id FROM fd.member WHERE is_deleted AND NOT is_bot".freeze

    LISTED_AGGREGATES = <<~SQL
      hit AS (
        SELECT user_id, place FROM unnest(LISTED_IDS) WITH ORDINALITY AS found(user_id, place)
      ),
      conduct AS (
        SELECT p.user_id,
               count(DISTINCT p.case_id) AS cases,
               count(*) FILTER (WHERE p.role = 'subject') AS subject_of,
               count(*) FILTER (WHERE p.role <> 'subject') AS logged_in,
               count(*) FILTER (WHERE p.role = 'subject' AND c.resolved_at IS NULL) AS open_cases,
               max(c.opened_at) AS last_case_at
        FROM fd.case_participants p
        JOIN fd.cases c ON c.id = p.case_id
        WHERE p.user_id IN (SELECT user_id FROM hit)
          AND (:category = 'any' OR c.category_key = :category)
        GROUP BY p.user_id
      ),
      acted AS (
        SELECT target_user_id AS user_id,
               count(*) AS actions,
               count(DISTINCT case_id) FILTER (
                 WHERE reversed_at IS NULL AND performed_at >= :prior_since
               ) AS priors
        FROM fd.actions
        WHERE target_user_id IN (SELECT user_id FROM hit)
        GROUP BY target_user_id
      ),
      held AS (
        SELECT subject_id AS user_id, count(*) AS in_force
        FROM fd.member_guards
        WHERE state IN ('live', 'lifting') AND subject_id IN (SELECT user_id FROM hit)
        GROUP BY subject_id
      ),
      noted AS (
        SELECT subject_user_id AS user_id, count(*) AS notes
        FROM fd.notes
        WHERE case_id IS NULL AND subject_user_id IN (SELECT user_id FROM hit) AND deleted_at IS NULL
        GROUP BY subject_user_id
      ),
      linked AS (
        SELECT user_id, count(*) AS links
        FROM fd.member_link_side
        WHERE score >= :strong AND user_id IN (SELECT user_id FROM hit)
        GROUP BY user_id
      ),
      people AS (SELECT user_id, place FROM hit),
      roster AS (
        SELECT people.user_id, people.place,
               coalesce(conduct.cases, 0) AS cases,
               coalesce(conduct.subject_of, 0) AS subject_of,
               coalesce(conduct.logged_in, 0) AS logged_in,
               coalesce(conduct.open_cases, 0) AS open_cases,
               conduct.last_case_at,
               coalesce(acted.actions, 0) AS actions,
               coalesce(held.in_force, 0) AS in_force,
               coalesce(acted.priors, 0) AS priors,
               coalesce(noted.notes, 0) AS notes,
               coalesce(linked.links, 0) AS links,
               coalesce(m.is_deleted, false) AS deactivated,
               m.display_name, m.handle
        FROM people
        LEFT JOIN conduct ON conduct.user_id = people.user_id
        LEFT JOIN acted ON acted.user_id = people.user_id
        LEFT JOIN held ON held.user_id = people.user_id
        LEFT JOIN noted ON noted.user_id = people.user_id
        LEFT JOIN linked ON linked.user_id = people.user_id
        LEFT JOIN fd.member m ON m.user_id = people.user_id
        LEFT JOIN analytics.dim_member_cohort dm ON dm.user_id = people.user_id
        LEFT JOIN fd.member_joins mj ON mj.user_id = people.user_id
        LEFT JOIN fd.member_seen ms ON ms.user_id = people.user_id
        LEFT JOIN LATERAL (
          SELECT last_active_at, messages_posted FROM analytics.fct_member_window w
          WHERE w.source = 'admin_analytics_member_range' AND w.user_id = people.user_id LIMIT 1
        ) w ON true
      )
    SQL

    CONTEXT_COLUMNS =
      ", coalesce(dm.cohort_at, mj.joined_at) AS cohort_at, " \
      "greatest(w.last_active_at, ms.last_post_at, ms.last_login_at) AS last_active_at, " \
      "w.messages_posted".freeze

    CONTEXT_JOIN = <<~SQL
      LEFT JOIN analytics.dim_member_cohort dm ON dm.user_id = people.user_id
      LEFT JOIN fd.member_joins mj ON mj.user_id = people.user_id
      LEFT JOIN fd.member_seen ms ON ms.user_id = people.user_id
      LEFT JOIN analytics.fct_member_window w
        ON w.user_id = people.user_id AND w.source = 'admin_analytics_member_range'
    SQL

    SORTS = {
      "messages" => "messages_posted",
      "subject" => "cases",
      "logged" => "logged_in",
      "actions" => "actions",
      "notes" => "notes"
    }.freeze

    NAMES = "m.display_name, m.handle".freeze
    DISPLAY_COLUMNS = "m.display_name, m.handle, m.title".freeze

    private

    def aggregates
      searching? ? listed("ARRAY[:hits]::text[]") : full_aggregates
    end

    def full_aggregates
      AGGREGATES.sub(NAMES, include_context? ? DISPLAY_COLUMNS + CONTEXT_COLUMNS : DISPLAY_COLUMNS)
        .sub("CONTEXT_JOIN", include_context? ? CONTEXT_JOIN : "")
        .sub("PEOPLE_FROM", people_from)
    end

    def listed(ids)
      LISTED_AGGREGATES.sub(NAMES, DISPLAY_COLUMNS + CONTEXT_COLUMNS).sub("LISTED_IDS") { ids }
    end

    def paged_ids
      "ARRAY(WITH #{full_aggregates} SELECT user_id FROM roster WHERE #{roster_where} " \
        "ORDER BY #{sort_order} LIMIT :limit OFFSET :offset)"
    end

    def include_context?
      searching? || !default?("tenure") || !default?("active") || self["sort"] == "messages"
    end

    def people_from
      return DEACTIVATED if self["state"] == "gone"

      conduct_only? ? TOUCHED : EVERYONE
    end

    def conduct_only?
      self["who"] != "everyone" || !default?("priors") || %w[open force noted].include?(self["state"])
    end

    def roster_where
      parts = ["1 = 1"]
      parts << "(subject_of > 0 OR logged_in > 0)" unless self["who"] == "everyone"
      parts << "priors >= #{self['priors'].to_i}" unless default?("priors")
      parts << state_clause if state_clause
      parts << tenure_clause unless default?("tenure")
      parts << active_clause unless default?("active")
      parts.compact.join(" AND ")
    end

    def state_clause
      case self["state"]
      when "open" then "open_cases > 0"
      when "force" then "in_force > 0"
      when "noted" then "notes > 0"
      when "clean" then "subject_of = 0 AND logged_in = 0"
      when "linked" then "links > 0"
      when "gone" then "deactivated"
      end
    end

    def tenure_clause
      days = "(current_date - cohort_at::date)"
      case self["tenure"]
      when "new" then "cohort_at IS NOT NULL AND #{days} < 31"
      when "year" then "cohort_at IS NOT NULL AND #{days} < 366"
      else "cohort_at IS NOT NULL AND #{days} >= 366"
      end
    end

    def active_clause
      days = "(current_date - last_active_at::date)"
      case self["active"]
      when "week" then "last_active_at IS NOT NULL AND #{days} <= 7"
      when "month" then "last_active_at IS NOT NULL AND #{days} <= 30"
      else "(last_active_at IS NULL OR #{days} > 90)"
      end
    end

    def roster_order
      return sort_order unless searching?

      "place, #{sort_order}"
    end

    def sort_order
      direction = descending? ? "DESC" : "ASC"
      tiebreak_direction = descending? ? "ASC" : "DESC"

      case self["sort"]
      when "name"
        "lower(coalesce(nullif(display_name, ''), nullif(handle, ''), user_id)) " \
          "#{descending? ? 'ASC' : 'DESC'}, user_id #{tiebreak_direction}"
      when *SORTS.keys
        "#{SORTS.fetch(self['sort'])} #{direction} NULLS LAST, user_id #{tiebreak_direction}"
      else
        "last_case_at #{direction} NULLS LAST, user_id #{tiebreak_direction}"
      end
    end

    def roster_binds
      binds = { category: self["category"], prior_since: Case::PRIOR_WINDOW.ago, strong: MemberLink::STRONG }
      searching? ? binds.merge(hits: hits) : binds
    end

    def select_rows(sql, extra = {})
      Case.connection.select_all(Case.sanitize_sql([sql, roster_binds.merge(extra)]))
    end
  end
end
