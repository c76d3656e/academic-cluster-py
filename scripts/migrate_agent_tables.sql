-- Idempotent migration for the production multi-agent workflow.
--
-- This script upgrades the original agent tables in place. It never drops
-- tables or rows. Legacy columns (for example input_args/output_result and
-- agent_memories) are intentionally left untouched so existing data remains
-- available during and after the application upgrade.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Agent executions
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    input_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    duration_ms BIGINT NOT NULL DEFAULT 0,
    token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_score DOUBLE PRECISION,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE
);

ALTER TABLE agent_executions
    ADD COLUMN IF NOT EXISTS project_id UUID,
    ADD COLUMN IF NOT EXISTS agent_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'running',
    ADD COLUMN IF NOT EXISTS input_state JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS output_state JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS duration_ms BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS token_usage JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE;

-- The first Agent prototype linked executions through pipeline_run_id and used
-- agent_type instead of project_id/status.  Resolve those aliases before the
-- new NOT NULL constraints are installed.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_executions'
          AND column_name = 'pipeline_run_id'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_executions ae
            SET project_id = pr.project_id
            FROM pipeline_runs pr
            WHERE ae.project_id IS NULL
              AND ae.pipeline_run_id = pr.id
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_executions'
          AND column_name = 'agent_type'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_executions
            SET agent_name = COALESCE(agent_name, agent_type, 'orchestrator')
            WHERE agent_name IS NULL
        $sql$;
    END IF;
END
$$;

-- Preserve corrupt/orphaned legacy rows without assigning them to a real user
-- project.  The deterministic quarantine project is hidden from normal users
-- because it has no owner, while administrators retain an audit trail.
DO $$
DECLARE
    orphan_project_id UUID := uuid_generate_v5(
        uuid_ns_url(),
        'academic-cluster:legacy-agent-orphan-project'
    );
BEGIN
    IF EXISTS (SELECT 1 FROM agent_executions WHERE project_id IS NULL) THEN
        INSERT INTO projects (id, name, description, status)
        VALUES (
            orphan_project_id,
            'Legacy Agent migration quarantine',
            'Orphaned Agent audit rows retained during schema migration',
            'interrupted'
        )
        ON CONFLICT (id) DO NOTHING;

        UPDATE agent_executions
        SET project_id = orphan_project_id
        WHERE project_id IS NULL;
    END IF;
END
$$;

UPDATE agent_executions
SET agent_name = COALESCE(agent_name, 'orchestrator'),
    status = CASE
        WHEN status IN ('pending', 'running') AND finished_at IS NOT NULL
            THEN 'succeeded'
        WHEN status IN ('pending', 'running') THEN 'interrupted'
        ELSE COALESCE(status, 'interrupted')
    END,
    input_state = COALESCE(input_state, '{}'::jsonb),
    output_state = COALESCE(output_state, '{}'::jsonb),
    duration_ms = COALESCE(duration_ms, 0),
    token_usage = COALESCE(token_usage, '{}'::jsonb),
    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
    finished_at = CASE
        WHEN status IN ('pending', 'running')
            THEN COALESCE(finished_at, CURRENT_TIMESTAMP)
        ELSE finished_at
    END,
    error_message = CASE
        WHEN status IN ('pending', 'running') THEN COALESCE(
            error_message,
            'Legacy active execution interrupted during schema migration'
        )
        ELSE error_message
    END
WHERE agent_name IS NULL
   OR status IS NULL
   OR status IN ('pending', 'running')
   OR input_state IS NULL
   OR output_state IS NULL
   OR duration_ms IS NULL
   OR token_usage IS NULL
   OR started_at IS NULL;

ALTER TABLE agent_executions
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN agent_name SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'running',
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN input_state SET DEFAULT '{}'::jsonb,
    ALTER COLUMN input_state SET NOT NULL,
    ALTER COLUMN output_state SET DEFAULT '{}'::jsonb,
    ALTER COLUMN output_state SET NOT NULL,
    ALTER COLUMN duration_ms SET DEFAULT 0,
    ALTER COLUMN duration_ms SET NOT NULL,
    ALTER COLUMN token_usage SET DEFAULT '{}'::jsonb,
    ALTER COLUMN token_usage SET NOT NULL,
    ALTER COLUMN started_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN started_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_executions_project_id_fkey'
          AND conrelid = 'agent_executions'::regclass
    ) THEN
        ALTER TABLE agent_executions
            ADD CONSTRAINT agent_executions_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
    END IF;
END
$$;

-- Link request-level LLM audit rows to their Agent execution.  The FK is added
-- only after agent_executions exists so fresh init and legacy upgrades share
-- the same ordering.
ALTER TABLE llm_calls
    ADD COLUMN IF NOT EXISTS execution_id UUID;

UPDATE llm_calls lc
SET execution_id = NULL
WHERE execution_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM agent_executions ae WHERE ae.id = lc.execution_id
  );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'llm_calls_execution_id_fkey'
          AND conrelid = 'llm_calls'::regclass
    ) THEN
        ALTER TABLE llm_calls
            ADD CONSTRAINT llm_calls_execution_id_fkey
            FOREIGN KEY (execution_id)
            REFERENCES agent_executions(id) ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_llm_calls_execution_id
    ON llm_calls(execution_id);

-- Preserve every execution record while resolving legacy duplicate active runs.
-- The newest active row remains active; older duplicates become interrupted.
WITH ranked_active AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY project_id
               ORDER BY started_at DESC NULLS LAST, id DESC
           ) AS active_rank
    FROM agent_executions
    WHERE status IN ('pending', 'running')
)
UPDATE agent_executions ae
SET status = 'interrupted',
    finished_at = COALESCE(ae.finished_at, CURRENT_TIMESTAMP),
    error_message = COALESCE(
        ae.error_message,
        'Migration resolved duplicate active execution for this project'
    )
FROM ranked_active ranked
WHERE ae.id = ranked.id
  AND ranked.active_rank > 1;

CREATE INDEX IF NOT EXISTS idx_agent_executions_project_id
    ON agent_executions(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_executions_agent_name
    ON agent_executions(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_executions_status
    ON agent_executions(status);
CREATE INDEX IF NOT EXISTS idx_agent_executions_project_started
    ON agent_executions(project_id, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_executions_project_active
    ON agent_executions(project_id)
    WHERE status IN ('pending', 'running');

-- ============================================================================
-- Supervisor decisions
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID NOT NULL REFERENCES agent_executions(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    decision VARCHAR(100) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE agent_decisions
    ADD COLUMN IF NOT EXISTS execution_id UUID,
    ADD COLUMN IF NOT EXISTS project_id UUID,
    ADD COLUMN IF NOT EXISTS agent_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS decision VARCHAR(100),
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_decisions'
          AND column_name = 'agent_execution_id'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_decisions
            SET execution_id = COALESCE(execution_id, agent_execution_id)
            WHERE execution_id IS NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_decisions'
          AND column_name = 'decision_type'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_decisions
            SET decision = COALESCE(decision, decision_type)
            WHERE decision IS NULL
        $sql$;
    END IF;
END
$$;

DO $$
DECLARE
    orphan_project_id UUID := uuid_generate_v5(
        uuid_ns_url(),
        'academic-cluster:legacy-agent-orphan-project'
    );
    orphan_execution_id UUID := uuid_generate_v5(
        uuid_ns_url(),
        'academic-cluster:legacy-agent-orphan-execution'
    );
BEGIN
    IF EXISTS (
        SELECT 1
        FROM agent_decisions ad
        WHERE ad.execution_id IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM agent_executions ae
               WHERE ae.id = ad.execution_id
           )
    ) THEN
        INSERT INTO projects (id, name, description, status)
        VALUES (
            orphan_project_id,
            'Legacy Agent migration quarantine',
            'Orphaned Agent audit rows retained during schema migration',
            'interrupted'
        )
        ON CONFLICT (id) DO NOTHING;

        INSERT INTO agent_executions (
            id, project_id, agent_name, status, input_state, output_state,
            duration_ms, token_usage, started_at, finished_at
        )
        VALUES (
            orphan_execution_id, orphan_project_id, 'migration', 'succeeded',
            '{}'::jsonb, '{}'::jsonb, 0, '{}'::jsonb,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (id) DO NOTHING;

        UPDATE agent_decisions ad
        SET execution_id = orphan_execution_id
        WHERE ad.execution_id IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM agent_executions ae
               WHERE ae.id = ad.execution_id
           );
    END IF;
END
$$;

UPDATE agent_decisions ad
SET project_id = COALESCE(ad.project_id, ae.project_id),
    agent_name = COALESCE(ad.agent_name, ae.agent_name, 'orchestrator'),
    created_at = COALESCE(ad.created_at, CURRENT_TIMESTAMP)
FROM agent_executions ae
WHERE ad.execution_id = ae.id
  AND (
      ad.project_id IS NULL
      OR ad.agent_name IS NULL
      OR ad.created_at IS NULL
  );

UPDATE agent_decisions
SET decision = COALESCE(decision, 'legacy_decision'),
    agent_name = COALESCE(agent_name, 'orchestrator'),
    created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
WHERE decision IS NULL OR agent_name IS NULL OR created_at IS NULL;

ALTER TABLE agent_decisions
    ALTER COLUMN execution_id SET NOT NULL,
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN agent_name SET NOT NULL,
    ALTER COLUMN decision SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_decisions_execution_id_fkey'
          AND conrelid = 'agent_decisions'::regclass
    ) THEN
        ALTER TABLE agent_decisions
            ADD CONSTRAINT agent_decisions_execution_id_fkey
            FOREIGN KEY (execution_id) REFERENCES agent_executions(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_decisions_project_id_fkey'
          AND conrelid = 'agent_decisions'::regclass
    ) THEN
        ALTER TABLE agent_decisions
            ADD CONSTRAINT agent_decisions_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_decisions_execution_id
    ON agent_decisions(execution_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_project_id
    ON agent_decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_project_created
    ON agent_decisions(project_id, created_at DESC);

-- ============================================================================
-- Agent tool-call audit log
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID NOT NULL REFERENCES agent_executions(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    duration_ms BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE agent_tool_calls
    ADD COLUMN IF NOT EXISTS execution_id UUID,
    ADD COLUMN IF NOT EXISTS project_id UUID,
    ADD COLUMN IF NOT EXISTS agent_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS tool_name VARCHAR(200),
    ADD COLUMN IF NOT EXISTS input_summary TEXT,
    ADD COLUMN IF NOT EXISTS output_summary TEXT,
    ADD COLUMN IF NOT EXISTS duration_ms BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'success',
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_tool_calls'
          AND column_name = 'agent_execution_id'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_tool_calls
            SET execution_id = COALESCE(execution_id, agent_execution_id)
            WHERE execution_id IS NULL
        $sql$;
    END IF;
END
$$;

-- Upgrade data written by the original schema without removing legacy columns.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_tool_calls'
          AND column_name = 'input_args'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_tool_calls
            SET input_summary = input_args::text
            WHERE input_summary IS NULL AND input_args IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_tool_calls'
          AND column_name = 'output_result'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_tool_calls
            SET output_summary = output_result::text
            WHERE output_summary IS NULL AND output_result IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_tool_calls'
          AND column_name = 'input_data'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_tool_calls
            SET input_summary = input_data::text
            WHERE input_summary IS NULL AND input_data IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_tool_calls'
          AND column_name = 'output_data'
    ) THEN
        EXECUTE $sql$
            UPDATE agent_tool_calls
            SET output_summary = output_data::text
            WHERE output_summary IS NULL AND output_data IS NOT NULL
        $sql$;
    END IF;
END
$$;

DO $$
DECLARE
    orphan_project_id UUID := uuid_generate_v5(
        uuid_ns_url(),
        'academic-cluster:legacy-agent-orphan-project'
    );
    orphan_execution_id UUID := uuid_generate_v5(
        uuid_ns_url(),
        'academic-cluster:legacy-agent-orphan-execution'
    );
BEGIN
    IF EXISTS (
        SELECT 1
        FROM agent_tool_calls atc
        WHERE atc.execution_id IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM agent_executions ae
               WHERE ae.id = atc.execution_id
           )
    ) THEN
        INSERT INTO projects (id, name, description, status)
        VALUES (
            orphan_project_id,
            'Legacy Agent migration quarantine',
            'Orphaned Agent audit rows retained during schema migration',
            'interrupted'
        )
        ON CONFLICT (id) DO NOTHING;

        INSERT INTO agent_executions (
            id, project_id, agent_name, status, input_state, output_state,
            duration_ms, token_usage, started_at, finished_at
        )
        VALUES (
            orphan_execution_id, orphan_project_id, 'migration', 'succeeded',
            '{}'::jsonb, '{}'::jsonb, 0, '{}'::jsonb,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (id) DO NOTHING;

        UPDATE agent_tool_calls atc
        SET execution_id = orphan_execution_id
        WHERE atc.execution_id IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM agent_executions ae
               WHERE ae.id = atc.execution_id
           );
    END IF;
END
$$;

UPDATE agent_tool_calls atc
SET project_id = COALESCE(atc.project_id, ae.project_id),
    agent_name = COALESCE(atc.agent_name, ae.agent_name, 'orchestrator'),
    duration_ms = COALESCE(atc.duration_ms, 0),
    status = COALESCE(atc.status, 'success'),
    created_at = COALESCE(atc.created_at, CURRENT_TIMESTAMP)
FROM agent_executions ae
WHERE atc.execution_id = ae.id
  AND (
      atc.project_id IS NULL
      OR atc.agent_name IS NULL
      OR atc.duration_ms IS NULL
      OR atc.status IS NULL
      OR atc.created_at IS NULL
  );

UPDATE agent_tool_calls
SET tool_name = COALESCE(tool_name, 'legacy_unknown_tool'),
    agent_name = COALESCE(agent_name, 'orchestrator'),
    duration_ms = COALESCE(duration_ms, 0),
    status = COALESCE(status, 'success'),
    created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
WHERE tool_name IS NULL
   OR agent_name IS NULL
   OR duration_ms IS NULL
   OR status IS NULL
   OR created_at IS NULL;

ALTER TABLE agent_tool_calls
    ALTER COLUMN execution_id SET NOT NULL,
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN agent_name SET NOT NULL,
    ALTER COLUMN tool_name SET NOT NULL,
    ALTER COLUMN duration_ms SET DEFAULT 0,
    ALTER COLUMN duration_ms SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'success',
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_tool_calls_execution_id_fkey'
          AND conrelid = 'agent_tool_calls'::regclass
    ) THEN
        ALTER TABLE agent_tool_calls
            ADD CONSTRAINT agent_tool_calls_execution_id_fkey
            FOREIGN KEY (execution_id) REFERENCES agent_executions(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_tool_calls_project_id_fkey'
          AND conrelid = 'agent_tool_calls'::regclass
    ) THEN
        ALTER TABLE agent_tool_calls
            ADD CONSTRAINT agent_tool_calls_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_execution_id
    ON agent_tool_calls(execution_id);
CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_project_id
    ON agent_tool_calls(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_tool_name
    ON agent_tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_project_created
    ON agent_tool_calls(project_id, created_at DESC);

-- ============================================================================
-- Stable project-to-paper ownership (replaces time-window based attribution)
-- ============================================================================

CREATE TABLE IF NOT EXISTS project_papers (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    first_seen_execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
    last_seen_execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
    source_query TEXT,
    relevance_score DOUBLE PRECISION,
    is_selected BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, paper_id)
);

ALTER TABLE project_papers
    ADD COLUMN IF NOT EXISTS first_seen_execution_id UUID,
    ADD COLUMN IF NOT EXISTS last_seen_execution_id UUID,
    ADD COLUMN IF NOT EXISTS source_query TEXT,
    ADD COLUMN IF NOT EXISTS relevance_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS is_selected BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

UPDATE project_papers
SET is_selected = COALESCE(is_selected, TRUE),
    metadata = COALESCE(metadata, '{}'::jsonb),
    created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
WHERE is_selected IS NULL
   OR metadata IS NULL
   OR created_at IS NULL
   OR updated_at IS NULL;

ALTER TABLE project_papers
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN paper_id SET NOT NULL,
    ALTER COLUMN is_selected SET DEFAULT TRUE,
    ALTER COLUMN is_selected SET NOT NULL,
    ALTER COLUMN metadata SET DEFAULT '{}'::jsonb,
    ALTER COLUMN metadata SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_papers_project_id_fkey'
          AND conrelid = 'project_papers'::regclass
    ) THEN
        ALTER TABLE project_papers
            ADD CONSTRAINT project_papers_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_papers_paper_id_fkey'
          AND conrelid = 'project_papers'::regclass
    ) THEN
        ALTER TABLE project_papers
            ADD CONSTRAINT project_papers_paper_id_fkey
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_papers_first_seen_execution_id_fkey'
          AND conrelid = 'project_papers'::regclass
    ) THEN
        ALTER TABLE project_papers
            ADD CONSTRAINT project_papers_first_seen_execution_id_fkey
            FOREIGN KEY (first_seen_execution_id)
            REFERENCES agent_executions(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_papers_last_seen_execution_id_fkey'
          AND conrelid = 'project_papers'::regclass
    ) THEN
        ALTER TABLE project_papers
            ADD CONSTRAINT project_papers_last_seen_execution_id_fkey
            FOREIGN KEY (last_seen_execution_id)
            REFERENCES agent_executions(id) ON DELETE SET NULL;
    END IF;
END
$$;

DO $$
DECLARE
    project_id_attnum SMALLINT;
    paper_id_attnum SMALLINT;
BEGIN
    SELECT attnum INTO project_id_attnum
    FROM pg_attribute
    WHERE attrelid = 'project_papers'::regclass
      AND attname = 'project_id'
      AND NOT attisdropped;

    SELECT attnum INTO paper_id_attnum
    FROM pg_attribute
    WHERE attrelid = 'project_papers'::regclass
      AND attname = 'paper_id'
      AND NOT attisdropped;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'project_papers'::regclass
          AND contype IN ('p', 'u')
          AND conkey = ARRAY[project_id_attnum, paper_id_attnum]::SMALLINT[]
    ) AND to_regclass('uq_project_papers_project_paper') IS NULL THEN
        CREATE UNIQUE INDEX uq_project_papers_project_paper
            ON project_papers(project_id, paper_id);
    END IF;
END
$$;
CREATE INDEX IF NOT EXISTS idx_project_papers_paper_id
    ON project_papers(paper_id);
CREATE INDEX IF NOT EXISTS idx_project_papers_first_execution
    ON project_papers(first_seen_execution_id);
CREATE INDEX IF NOT EXISTS idx_project_papers_last_execution
    ON project_papers(last_seen_execution_id);
CREATE INDEX IF NOT EXISTS idx_project_papers_project_selected
    ON project_papers(project_id, is_selected, created_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'update_project_papers_updated_at'
          AND tgrelid = 'project_papers'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER update_project_papers_updated_at
            BEFORE UPDATE ON project_papers
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;

COMMIT;
