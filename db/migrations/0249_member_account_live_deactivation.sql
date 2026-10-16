CREATE OR REPLACE VIEW fd.member_account AS
SELECT d.user_id,
       coalesce(d.invite_pending, false) AS invite_pending,
       d.claimed_at,
       coalesce(m.is_deleted, coalesce(d.is_deleted, false) OR d.deactivated_at IS NOT NULL) AS deactivated,
       s.last_login_at,
       s.last_post_at
FROM raw.member_dim d
LEFT JOIN fd.member m ON m.user_id = d.user_id
LEFT JOIN fd.member_seen s ON s.user_id = d.user_id;
