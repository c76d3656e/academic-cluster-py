-- Security migration: organizations, tenant context and PostgreSQL RLS.
-- Idempotent and safe to run before every application deployment.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_user
    ON organization_memberships(user_id, is_active);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_organization_id UUID
    REFERENCES organizations(id) ON DELETE SET NULL;
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS organization_id UUID
    REFERENCES organizations(id) ON DELETE RESTRICT;

INSERT INTO organizations (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'System quarantine', 'system-quarantine')
ON CONFLICT (id) DO NOTHING;

INSERT INTO organizations (id, name, slug, created_by)
SELECT
    uuid_generate_v5(uuid_ns_url(), 'academic-cluster:user:' || u.id::text),
    COALESCE(NULLIF(u.full_name, ''), u.email),
    'personal-' || replace(u.id::text, '-', ''),
    u.id
FROM users u
ON CONFLICT (id) DO NOTHING;

INSERT INTO organization_memberships (organization_id, user_id, role)
SELECT
    uuid_generate_v5(uuid_ns_url(), 'academic-cluster:user:' || u.id::text),
    u.id,
    'owner'
FROM users u
ON CONFLICT (organization_id, user_id) DO UPDATE
SET role = 'owner', is_active = TRUE;

UPDATE users
SET default_organization_id = uuid_generate_v5(
    uuid_ns_url(), 'academic-cluster:user:' || id::text
)
WHERE default_organization_id IS NULL;

UPDATE projects p
SET organization_id = COALESCE(
    u.default_organization_id,
    '00000000-0000-0000-0000-000000000001'::uuid
)
FROM users u
WHERE p.user_id = u.id AND p.organization_id IS NULL;
UPDATE projects
SET organization_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE organization_id IS NULL;
ALTER TABLE projects ALTER COLUMN organization_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_projects_organization
    ON projects(organization_id, created_at DESC);

CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS UUID
LANGUAGE SQL STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_user_id', TRUE), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_current_organization_id()
RETURNS UUID
LANGUAGE SQL STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_organization_id', TRUE), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_context_is_admin()
RETURNS BOOLEAN
LANGUAGE SQL STABLE
AS $$
    SELECT COALESCE(current_setting('app.is_admin', TRUE), 'false') = 'true'
$$;

CREATE OR REPLACE FUNCTION app_tenant_access(target UUID)
RETURNS BOOLEAN
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT app_context_is_admin() OR EXISTS (
        SELECT 1
        FROM organization_memberships membership
        WHERE membership.organization_id = target
          AND membership.user_id = app_current_user_id()
          AND membership.is_active = TRUE
    )
$$;

CREATE OR REPLACE FUNCTION app_project_access(target UUID)
RETURNS BOOLEAN
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM projects project
        WHERE project.id = target
          AND app_tenant_access(project.organization_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_outline_access(target UUID)
RETURNS BOOLEAN
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM outlines outline
        WHERE outline.id = target AND app_project_access(outline.project_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_cluster_access(target UUID)
RETURNS BOOLEAN
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM clusters cluster
        WHERE cluster.id = target AND app_project_access(cluster.project_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_pipeline_run_access(target UUID)
RETURNS BOOLEAN
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM pipeline_runs run
        WHERE run.id = target AND app_project_access(run.project_id)
    )
$$;

ALTER TABLE kg_entities
    ADD COLUMN IF NOT EXISTS organization_id UUID
    REFERENCES organizations(id) ON DELETE CASCADE
    DEFAULT app_current_organization_id();
ALTER TABLE kg_relations
    ADD COLUMN IF NOT EXISTS organization_id UUID
    REFERENCES organizations(id) ON DELETE CASCADE
    DEFAULT app_current_organization_id();
ALTER TABLE llm_calls
    ADD COLUMN IF NOT EXISTS organization_id UUID
    REFERENCES organizations(id) ON DELETE SET NULL
    DEFAULT app_current_organization_id();

UPDATE kg_entities
SET organization_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE organization_id IS NULL;
UPDATE kg_relations
SET organization_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE organization_id IS NULL;
UPDATE llm_calls call
SET organization_id = project.organization_id
FROM projects project
WHERE call.project_id = project.id AND call.organization_id IS NULL;
UPDATE llm_calls
SET organization_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE organization_id IS NULL;

ALTER TABLE kg_entities ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE kg_relations ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE llm_calls ALTER COLUMN organization_id SET NOT NULL;
DROP INDEX IF EXISTS idx_kg_entities_normalized_name;
CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_entities_org_normalized_name
    ON kg_entities(organization_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_kg_relations_organization
    ON kg_relations(organization_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_organization
    ON llm_calls(organization_id, created_at DESC);

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON organizations;
CREATE POLICY tenant_isolation ON organizations
    USING (app_tenant_access(id))
    WITH CHECK (app_context_is_admin() OR created_by = app_current_user_id());

ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_memberships FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON organization_memberships;
CREATE POLICY tenant_isolation ON organization_memberships
    USING (app_tenant_access(organization_id))
    WITH CHECK (
        app_context_is_admin()
        OR (
            user_id = app_current_user_id()
            AND organization_id = app_current_organization_id()
        )
    );

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON projects;
CREATE POLICY tenant_isolation ON projects
    USING (app_tenant_access(organization_id))
    WITH CHECK (app_tenant_access(organization_id));

ALTER TABLE kg_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_entities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON kg_entities;
CREATE POLICY tenant_isolation ON kg_entities
    USING (app_tenant_access(organization_id))
    WITH CHECK (app_tenant_access(organization_id));

ALTER TABLE kg_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_relations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON kg_relations;
CREATE POLICY tenant_isolation ON kg_relations
    USING (app_tenant_access(organization_id))
    WITH CHECK (app_tenant_access(organization_id));

ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON llm_calls;
CREATE POLICY tenant_isolation ON llm_calls
    USING (app_tenant_access(organization_id))
    WITH CHECK (app_tenant_access(organization_id));

DO $policies$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'clusters', 'outlines', 'evidence_cards', 'pipeline_checkpoints',
        'pipeline_audit_log', 'pipeline_runs', 'agent_executions',
        'agent_decisions', 'agent_tool_calls', 'project_papers'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (app_project_access(project_id)) WITH CHECK (app_project_access(project_id))',
            table_name
        );
    END LOOP;
END
$policies$;

ALTER TABLE cluster_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON cluster_assignments;
CREATE POLICY tenant_isolation ON cluster_assignments
    USING (app_cluster_access(cluster_id))
    WITH CHECK (app_cluster_access(cluster_id));

ALTER TABLE written_content ENABLE ROW LEVEL SECURITY;
ALTER TABLE written_content FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON written_content;
CREATE POLICY tenant_isolation ON written_content
    USING (app_outline_access(outline_id))
    WITH CHECK (app_outline_access(outline_id));

ALTER TABLE node_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE node_executions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON node_executions;
CREATE POLICY tenant_isolation ON node_executions
    USING (app_pipeline_run_access(pipeline_run_id))
    WITH CHECK (app_pipeline_run_access(pipeline_run_id));
