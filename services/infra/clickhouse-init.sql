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