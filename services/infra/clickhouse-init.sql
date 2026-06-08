CREATE DATABASE IF NOT EXISTS ra1_analytics;

CREATE TABLE IF NOT EXISTS ra1_analytics.usage_events (
    id UUID DEFAULT generateUUIDv4(),
    event_type String,
    user_id Nullable(String),
    model_id Nullable(String),
    provider_id Nullable(String),
    input_tokens Nullable(UInt32),
    output_tokens Nullable(UInt32),
    latency_ms Nullable(UInt32),
    status String,
    fallback_triggered UInt8 DEFAULT 0,
    fallback_from Nullable(String),
    fallback_to Nullable(String),
    byok_used UInt8 DEFAULT 0,
    payload Nullable(String),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (id, created_at)
TTL created_at + toIntervalYear(2);

CREATE TABLE IF NOT EXISTS ra1_analytics.credential_access_events (
    event_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime DEFAULT now(),
    user_id Nullable(String),
    key_name String,
    success UInt8,
    error_code Nullable(String)
) ENGINE = MergeTree()
ORDER BY (event_id, timestamp)
TTL timestamp + INTERVAL 2 YEAR;

-- ────────────────────────────────────────────────────────────────────────────
-- RA1 ATRS — Audit Trace + Replay System.
-- Append-only observability backbone. Every row is an immutable record of a
-- single event in the RA1 system. NO UPDATE / DELETE in application code.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ra1_analytics.audit_trace (
    log_id        UUID         DEFAULT generateUUIDv4(),
    timestamp     Int64        NOT NULL,  -- UTC milliseconds
    session_id    Nullable(String),
    habitat_id    Nullable(String),
    engine        LowCardinality(String) NOT NULL,
    event_type    LowCardinality(String) NOT NULL,
    entity_ref    Nullable(String),       -- strict pattern: <type>:<id>
    status        LowCardinality(String) NOT NULL,  -- success|failure|blocked|partial
    duration_ms   Nullable(Int32),
    error_code    Nullable(String),
    metadata      Nullable(String)        -- JSON-serialised, scrubbed
) ENGINE = MergeTree()
ORDER BY (log_id, timestamp)
TTL toDateTime(timestamp / 1000) + INTERVAL 2 YEAR;
