CREATE DATABASE ra1_litellm;
GRANT ALL PRIVILEGES ON DATABASE ra1_litellm TO ra1;

CREATE DATABASE langfuse;
GRANT ALL PRIVILEGES ON DATABASE langfuse TO ra1;

-- ────────────────────────────────────────────────────────────────────────────
-- RA1 core schema (lives in the default `ra1` database created by the env).
-- These tables are idempotent: safe to re-run on a fresh volume or on an
-- existing volume that already has them.
-- ────────────────────────────────────────────────────────────────────────────

-- Credential Vault — encrypted-at-rest credential storage, isolated by owner.
CREATE TABLE IF NOT EXISTS vault_entries (
    vault_id                  UUID         PRIMARY KEY,
    owner_id                  TEXT         NOT NULL,
    credential_type           TEXT         NOT NULL,
    encrypted_value           TEXT         NOT NULL,
    connector_ref             TEXT         NULL,
    label                     TEXT         NOT NULL,
    status                    TEXT         NOT NULL DEFAULT 'active',
    expires_at                TIMESTAMPTZ  NULL,
    refresh_token_encrypted   TEXT         NULL,
    refresh_status            TEXT         NOT NULL DEFAULT 'none',
    last_used_at              TIMESTAMPTZ  NULL,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT vault_entries_owner_label_uk UNIQUE (owner_id, label),
    CONSTRAINT vault_entries_status_chk     CHECK (status IN ('active','rotated','revoked','expired')),
    CONSTRAINT vault_entries_type_chk       CHECK (credential_type IN
        ('oauth_token','api_key','model_api_key','webhook_secret','service_account','custom'))
);

CREATE INDEX IF NOT EXISTS vault_entries_owner_idx ON vault_entries (owner_id);
CREATE INDEX IF NOT EXISTS vault_entries_status_idx ON vault_entries (owner_id, status);

-- ATRS outbox — durability fallback when ClickHouse is unavailable.
-- A background worker (future phase) will replay rows from here into
-- ra1_analytics.audit_trace on ClickHouse.
CREATE TABLE IF NOT EXISTS atrs_outbox (
    outbox_id     BIGSERIAL    PRIMARY KEY,
    payload       JSONB        NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    replayed_at   TIMESTAMPTZ  NULL
);

CREATE INDEX IF NOT EXISTS atrs_outbox_unreplayed_idx
    ON atrs_outbox (created_at)
    WHERE replayed_at IS NULL;

-- Model Catalog — metadata and status for AI models.
-- Models can be linked to vault entries for API key resolution (BYOK).
CREATE TABLE IF NOT EXISTS model_catalog (
    model_id                  TEXT         PRIMARY KEY,
    provider                  TEXT         NOT NULL,
    display_name              TEXT         NOT NULL,
    status                    TEXT         NOT NULL DEFAULT 'active',
    capabilities              TEXT[]       NOT NULL DEFAULT '{}',
    credential_ref            UUID         NULL,
    context_window            INTEGER      NOT NULL DEFAULT 0,
    input_price               NUMERIC(10,6) NOT NULL DEFAULT 0.0,
    output_price              NUMERIC(10,6) NOT NULL DEFAULT 0.0,
    speed                     TEXT         NOT NULL DEFAULT 'standard',
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT model_catalog_status_chk CHECK (status IN ('discovered','active','deprecated','removed')),
    CONSTRAINT model_catalog_speed_chk  CHECK (speed IN ('instant','fast','standard','slow'))
);

CREATE INDEX IF NOT EXISTS model_catalog_status_idx ON model_catalog (status);
CREATE INDEX IF NOT EXISTS model_catalog_provider_idx ON model_catalog (provider);
CREATE INDEX IF NOT EXISTS model_catalog_credential_idx ON model_catalog (credential_ref);

-- Memory Engine — atomic knowledge records with confidence-scored lanes.
CREATE TABLE IF NOT EXISTS memory_records (
    entity_id       UUID         PRIMARY KEY,
    habitat_id      UUID         NOT NULL,
    user_id         UUID         NOT NULL,
    entity_type     TEXT         NOT NULL,
    attribute       TEXT         NOT NULL,
    value           JSONB        NOT NULL,
    knowledge_type  TEXT         NOT NULL,
    confidence      REAL         NOT NULL DEFAULT 0.5,
    source          TEXT         NOT NULL,
    provenance      TEXT         NOT NULL,
    ttl             TIMESTAMPTZ  NULL,
    lock_status     BOOLEAN      NOT NULL DEFAULT FALSE,
    links           JSONB        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT memory_records_knowledge_type_chk 
        CHECK (knowledge_type IN ('FACT','DERIVED_FACT','HYPOTHESIS','OPINION','RECOMMENDATION','PROCEDURE','TRACE')),
    CONSTRAINT memory_records_source_chk 
        CHECK (source IN ('user','connector','agent','flow','inference')),
    CONSTRAINT memory_records_confidence_range 
        CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS memory_records_habitat_idx ON memory_records (habitat_id);
CREATE INDEX IF NOT EXISTS memory_records_user_idx ON memory_records (user_id);
CREATE INDEX IF NOT EXISTS memory_records_entity_type_idx ON memory_records (entity_type);
CREATE INDEX IF NOT EXISTS memory_records_confidence_idx ON memory_records (confidence);

-- Persona Engine — archetype-driven identity profiles.
CREATE TABLE IF NOT EXISTS personas (
    persona_id     UUID         PRIMARY KEY,
    user_id        UUID         NOT NULL,
    habitat_id     UUID         NULL,
    name           TEXT         NOT NULL,
    profession     TEXT         NOT NULL,
    industry       TEXT         NOT NULL,
    archetype_blend JSONB        NOT NULL,
    tone_rules     JSONB        NOT NULL DEFAULT '[]',
    rules          JSONB        NOT NULL DEFAULT '[]',
    scope          TEXT         NOT NULL DEFAULT 'global',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT persona_scope_chk CHECK (scope IN ('global', 'habitat', 'private'))
);

CREATE INDEX IF NOT EXISTS personas_user_idx ON personas (user_id);
CREATE INDEX IF NOT EXISTS personas_habitat_idx ON personas (user_id, habitat_id);

-- Knowledge Base — explicit user-curated knowledge assets.
CREATE TABLE IF NOT EXISTS knowledge_items (
    item_id      UUID         PRIMARY KEY,
    user_id      UUID         NOT NULL,
    habitat_id   UUID         NOT NULL,
    content_type TEXT         NOT NULL,
    content      JSONB        NOT NULL,
    tags         TEXT[]       NOT NULL DEFAULT '{}',
    collections  TEXT[]       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_content_type_chk CHECK (content_type IN ('document', 'note', 'web_clip', 'structured'))
);

CREATE INDEX IF NOT EXISTS knowledge_items_user_idx ON knowledge_items (user_id);
CREATE INDEX IF NOT EXISTS knowledge_items_habitat_idx ON knowledge_items (habitat_id);
CREATE INDEX IF NOT EXISTS knowledge_items_tags_idx ON knowledge_items USING GIN (tags);
CREATE INDEX IF NOT EXISTS knowledge_items_search_idx ON knowledge_items USING GIN (content);

-- Notifications — system-level state flags, exceptions, and blocks routing.
CREATE TABLE IF NOT EXISTS notifications (
    notification_id   UUID         PRIMARY KEY,
    user_id           UUID         NOT NULL,
    habitat_id        UUID         NULL,
    priority          TEXT         NOT NULL CHECK (priority IN ('P0_BLOCK','P1_URGENT','P2_INFORM','P3_NOTICE','P_SILENT')),
    source_engine     TEXT         NOT NULL,
    title             TEXT         NOT NULL,
    message           TEXT         NOT NULL,
    status            TEXT         NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','resolved')),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id);
CREATE INDEX IF NOT EXISTS notifications_status_idx ON notifications (status);

-- Recommendations — non-blocking proactive architectural optimization suggestions.
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id UUID         PRIMARY KEY,
    user_id           UUID         NOT NULL,
    habitat_id        UUID         NULL,
    domain            TEXT         NOT NULL CHECK (domain IN ('MODEL','PERSONA','SKILLS','ENVIRONMENT')),
    suggestion_text   TEXT         NOT NULL,
    trigger_context   JSONB        NOT NULL,
    status            TEXT         NOT NULL DEFAULT 'active' CHECK (status IN ('active','accepted','dismissed')),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recommendations_user_idx ON recommendations (user_id);
CREATE INDEX IF NOT EXISTS recommendations_status_idx ON recommendations (status);
