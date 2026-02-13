-- 004_repeater_telemetry.sql
-- Stores telemetry data from monitored repeaters in key-value format.
-- Each metric is stored as a separate row with a metric_key and metric_value.

CREATE TABLE IF NOT EXISTS repeater_telemetry
(
    recorded_at   DateTime64(3, 'UTC')        DEFAULT now64(),
    repeater_id   UUID,
    repeater_name String,
    metric_key    LowCardinality(String),
    metric_value  Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(recorded_at)
ORDER BY (repeater_id, recorded_at, metric_key)
SETTINGS index_granularity = 8192;
