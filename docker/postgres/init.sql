-- Academic Cluster Database Initialization with pgvector

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_email ON users(email);

-- Refresh tokens table
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);

-- User activities table
CREATE TABLE IF NOT EXISTS user_activities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_user_activities_user_id ON user_activities(user_id);
CREATE INDEX idx_user_activities_created_at ON user_activities(created_at);

-- Papers table
CREATE TABLE IF NOT EXISTS papers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id VARCHAR(255) UNIQUE,
    source VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    authors JSONB,
    publication_date DATE,
    journal VARCHAR(500),
    doi VARCHAR(255),
    url TEXT,
    pdf_url TEXT,
    citation_count INTEGER DEFAULT 0,
    reference_count INTEGER DEFAULT 0,
    influential_citation_count INTEGER DEFAULT 0,
    fields_of_study JSONB,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Embeddings table with pgvector
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    model_name VARCHAR(100) NOT NULL,
    vector vector(1024),
    dimensions INTEGER NOT NULL DEFAULT 1024,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, model_name)
);

-- Create HNSW index for fast vector search
CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON embeddings USING hnsw (vector vector_cosine_ops);

-- Clusters table
CREATE TABLE IF NOT EXISTS clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    name VARCHAR(255),
    description TEXT,
    algorithm VARCHAR(50) NOT NULL,
    parameters JSONB,
    quality_score FLOAT,
    size INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Cluster assignments
CREATE TABLE IF NOT EXISTS cluster_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_id UUID REFERENCES clusters(id) ON DELETE CASCADE,
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    confidence FLOAT,
    is_representative BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cluster_id, paper_id)
);

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    query TEXT,
    status VARCHAR(50) DEFAULT 'created',
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_projects_user_id ON projects(user_id);

-- Outlines table
CREATE TABLE IF NOT EXISTS outlines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    sections JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Written content table
CREATE TABLE IF NOT EXISTS written_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    outline_id UUID REFERENCES outlines(id) ON DELETE CASCADE,
    section_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    word_count INTEGER,
    quality_score FLOAT,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Evidence cards table
CREATE TABLE IF NOT EXISTS evidence_cards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    claim TEXT,
    evidence_span TEXT,
    method TEXT,
    metric TEXT,
    limitation TEXT,
    confidence FLOAT,
    cluster_id UUID REFERENCES clusters(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Community memories synthesized from clusters, evidence cards, KG, and paper metadata
CREATE TABLE IF NOT EXISTS community_memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    cluster_id UUID REFERENCES clusters(id) ON DELETE CASCADE,
    summary TEXT,
    method_families JSONB NOT NULL DEFAULT '[]'::jsonb,
    key_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
    limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
    future_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
    foundation_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
    development_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
    frontier_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
    representative_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
    cross_community_links JSONB NOT NULL DEFAULT '[]'::jsonb,
    proof_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, cluster_id)
);

-- Knowledge graph entities
CREATE TABLE IF NOT EXISTS kg_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    paper_ids UUID[],
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge graph relations
CREATE TABLE IF NOT EXISTS kg_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID REFERENCES kg_entities(id) ON DELETE CASCADE,
    target_entity_id UUID REFERENCES kg_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(50) NOT NULL,
    paper_ids UUID[],
    confidence FLOAT DEFAULT 1.0,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Pipeline checkpoints table
CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    node_name VARCHAR(100) NOT NULL,
    state_snapshot JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'in_progress',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, node_name)
);

-- Pipeline audit log table
CREATE TABLE IF NOT EXISTS pipeline_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    node_name VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX idx_papers_external_id ON papers(external_id);
CREATE INDEX idx_papers_source ON papers(source);
CREATE INDEX idx_papers_title_trgm ON papers USING gin(title gin_trgm_ops);
CREATE INDEX idx_embeddings_paper_id ON embeddings(paper_id);
CREATE INDEX idx_cluster_assignments_cluster_id ON cluster_assignments(cluster_id);
CREATE INDEX idx_cluster_assignments_paper_id ON cluster_assignments(paper_id);
CREATE INDEX idx_outlines_project_id ON outlines(project_id);
CREATE INDEX idx_written_content_outline_id ON written_content(outline_id);
CREATE INDEX idx_evidence_cards_paper_id ON evidence_cards(paper_id);
CREATE INDEX idx_evidence_cards_project_id ON evidence_cards(project_id);
CREATE UNIQUE INDEX idx_evidence_cards_project_paper ON evidence_cards(project_id, paper_id)
    WHERE project_id IS NOT NULL;
CREATE INDEX idx_community_memories_project_id ON community_memories(project_id);
CREATE INDEX idx_community_memories_cluster_id ON community_memories(cluster_id);
CREATE UNIQUE INDEX idx_kg_entities_normalized_name ON kg_entities(normalized_name);
CREATE INDEX idx_kg_relations_source ON kg_relations(source_entity_id);
CREATE INDEX idx_kg_relations_target ON kg_relations(target_entity_id);
CREATE INDEX idx_pipeline_checkpoints_project ON pipeline_checkpoints(project_id);
CREATE INDEX idx_pipeline_checkpoints_node ON pipeline_checkpoints(project_id, node_name);
CREATE INDEX idx_pipeline_audit_log_project ON pipeline_audit_log(project_id);
CREATE INDEX idx_pipeline_audit_log_node ON pipeline_audit_log(project_id, node_name);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
CREATE TRIGGER update_papers_updated_at BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_outlines_updated_at BEFORE UPDATE ON outlines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_written_content_updated_at BEFORE UPDATE ON written_content
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_pipeline_checkpoints_updated_at BEFORE UPDATE ON pipeline_checkpoints
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Observability Tables: Pipeline Runs / Node Executions / LLM Calls
-- ============================================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    topic VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    error_message TEXT,
    total_nodes INTEGER DEFAULT 0,
    completed_nodes INTEGER DEFAULT 0,
    failed_nodes INTEGER DEFAULT 0,
    total_prompt_tokens BIGINT DEFAULT 0,
    total_completion_tokens BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,
    total_cost NUMERIC(12,6) DEFAULT 0,
    total_llm_calls INTEGER DEFAULT 0,
    elapsed_seconds FLOAT,
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    created_by UUID
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created ON pipeline_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS node_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    node_name VARCHAR(100) NOT NULL,
    node_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    index INTEGER,
    error_message TEXT,
    error_traceback TEXT,
    input_summary JSONB,
    output_summary JSONB,
    prompt_tokens BIGINT DEFAULT 0,
    completion_tokens BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,
    cost NUMERIC(12,6) DEFAULT 0,
    llm_calls_count INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    elapsed_ms BIGINT,
    metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_node_exec_run ON node_executions(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_node_exec_name ON node_executions(node_name);
CREATE INDEX IF NOT EXISTS idx_node_exec_status ON node_executions(status);

CREATE TABLE IF NOT EXISTS llm_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID,
    pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    node_execution_id UUID REFERENCES node_executions(id) ON DELETE CASCADE,
    node_name VARCHAR(100),
    call_type VARCHAR(20) NOT NULL,
    provider_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(200) NOT NULL,
    requested_model VARCHAR(200),
    upstream_model VARCHAR(200),
    api_base_url VARCHAR(500),
    api_key_hint VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    error_message TEXT,
    http_status_code INTEGER,
    is_stream BOOLEAN DEFAULT FALSE,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost NUMERIC(12,8) DEFAULT 0,
    latency_ms BIGINT NOT NULL,
    first_token_ms BIGINT,
    input_preview TEXT,
    output_preview TEXT,
    request_metadata JSONB,
    retry_of UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_project ON llm_calls(project_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_node ON llm_calls(node_execution_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_node_name ON llm_calls(node_name);
CREATE INDEX IF NOT EXISTS idx_llm_calls_provider ON llm_calls(provider_name, model_name);
CREATE INDEX IF NOT EXISTS idx_llm_calls_requested_model ON llm_calls(requested_model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_status ON llm_calls(status);

-- ============================================================================
-- Provider Registry: 管理 LLM/Embedding/Rerank Provider 配置
-- ============================================================================

CREATE TABLE IF NOT EXISTS provider_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind            VARCHAR(20) NOT NULL,           -- llm / embedding / rerank
    display_name    VARCHAR(100) NOT NULL,
    base_url        TEXT NOT NULL,
    model           VARCHAR(200),
    api_key_enc     TEXT,                            -- Fernet 加密
    is_enabled      BOOLEAN DEFAULT true,
    priority        INTEGER DEFAULT 100,
    rpm_limit       INTEGER DEFAULT 10,
    weight          INTEGER DEFAULT 1,
    extra_keys      JSONB DEFAULT '[]',              -- 多 Key（Fernet 加密数组）
    key_strategy    VARCHAR(20) DEFAULT 'round_robin',
    health_status   VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMPTZ,
    last_error      TEXT,
    failure_count   INTEGER DEFAULT 0,
    auto_ban        BOOLEAN DEFAULT true,
    cooldown_until  TIMESTAMPTZ,
    test_model      VARCHAR(200),
    input_price_per_m  DOUBLE PRECISION DEFAULT 0,
    output_price_per_m DOUBLE PRECISION DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_provider_registry_kind ON provider_registry(kind);
CREATE INDEX IF NOT EXISTS idx_provider_registry_enabled ON provider_registry(is_enabled);
CREATE INDEX IF NOT EXISTS idx_provider_registry_health ON provider_registry(health_status);

CREATE TRIGGER update_provider_registry_updated_at
    BEFORE UPDATE ON provider_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function for KNN vector search
CREATE OR REPLACE FUNCTION search_similar_papers(
    query_embedding vector(1024),
    match_count INTEGER DEFAULT 10,
    match_threshold FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    paper_id UUID,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.paper_id,
        1 - (e.vector <=> query_embedding) AS similarity
    FROM embeddings e
    WHERE 1 - (e.vector <=> query_embedding) > match_threshold
    ORDER BY e.vector <=> query_embedding
    LIMIT match_count;
END;
$$;
