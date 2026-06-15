-- Migration: Add provider_registry table
-- Run: psql -d academic_cluster -f scripts/migrate_provider_registry.sql

CREATE TABLE IF NOT EXISTS provider_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind            VARCHAR(20) NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    base_url        TEXT NOT NULL,
    model           VARCHAR(200),
    api_key_enc     TEXT,
    is_enabled      BOOLEAN DEFAULT true,
    priority        INTEGER DEFAULT 100,
    rpm_limit       INTEGER DEFAULT 10,
    weight          INTEGER DEFAULT 1,
    extra_keys      JSONB DEFAULT '[]',
    key_strategy    VARCHAR(20) DEFAULT 'round_robin',
    health_status   VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMPTZ,
    last_error      TEXT,
    failure_count   INTEGER DEFAULT 0,
    auto_ban        BOOLEAN DEFAULT true,
    cooldown_until  TIMESTAMPTZ,
    test_model      VARCHAR(200),
    metadata        JSONB DEFAULT '{}',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_provider_registry_kind ON provider_registry(kind);
CREATE INDEX IF NOT EXISTS idx_provider_registry_enabled ON provider_registry(is_enabled);
CREATE INDEX IF NOT EXISTS idx_provider_registry_health ON provider_registry(health_status);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_provider_registry_updated_at'
    ) THEN
        CREATE TRIGGER update_provider_registry_updated_at
            BEFORE UPDATE ON provider_registry
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;
