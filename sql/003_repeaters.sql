-- 003_repeaters.sql
-- Stores repeaters to be monitored for telemetry.
-- Engine: ReplacingMergeTree (deduplicates by id on merge).

CREATE TABLE IF NOT EXISTS repeaters
(
    id          UUID                  DEFAULT generateUUIDv4(),
    name        String,
    public_key  String,
    password    String                DEFAULT '',
    enabled     Bool                  DEFAULT true,
    created_at  DateTime64(3, 'UTC')  DEFAULT now64()
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (id);
