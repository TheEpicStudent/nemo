ALTER TABLE fd.ip_network DROP CONSTRAINT IF EXISTS ip_network_source_known;
ALTER TABLE fd.ip_network ADD CONSTRAINT ip_network_source_known
    CHECK (source IN ('anomaly', 'tor_list', 'curated', 'lists_vpn', 'ipinfo', 'default'));
