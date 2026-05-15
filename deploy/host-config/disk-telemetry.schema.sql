-- host_disk_telemetry — Hetzner host disk usage time series.
-- Populated hourly by /opt/nbne/scripts/disk-telemetry.sh.
-- Consumed by /opt/nbne/scripts/disk-alert.sh and (later) a Deek dashboard.

CREATE TABLE IF NOT EXISTS host_disk_telemetry (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category   TEXT NOT NULL CHECK (category IN (
                   'filesystem_used',
                   'filesystem_total',
                   'docker_images',
                   'docker_containers',
                   'docker_volumes',
                   'docker_build_cache',
                   'ark_backups'
               )),
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_host_disk_telemetry_ts_cat
    ON host_disk_telemetry (ts DESC, category);

CREATE INDEX IF NOT EXISTS idx_host_disk_telemetry_category_ts
    ON host_disk_telemetry (category, ts DESC);

-- 90-day retention is plenty: enough to see seasonal patterns and
-- post-mortem any incident in the rolling quarter. Keep this minimal
-- — telemetry rows aren't worth backing up.
COMMENT ON TABLE host_disk_telemetry IS
    'Hourly Hetzner host disk usage by category. 90-day retention. '
    'Written by /opt/nbne/scripts/disk-telemetry.sh. '
    'Schema in deek/deploy/host-config/disk-telemetry.schema.sql.';
