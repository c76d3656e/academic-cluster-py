-- Academic Cluster Database Initialization

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Papers table
CREATE TABLE IF NOT EXISTS papers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id VARCHAR(255) UNIQUE,
    source VARCHAR(50) NOT NULL, -- 'semantic_scholar', 'pubmed', 'arxiv'
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

-- Create indexes for papers
CREATE INDEX idx_papers_external_id ON papers(external_id);
CREATE INDEX idx_papers_source ON papers(source);
CREATE INDEX idx_papers_title_trgm ON papers USING gin(title gin_trgm_ops);
CREATE INDEX idx_papers_publication_date ON papers(publication_date);
CREATE INDEX idx_papers_citation_count ON papers(citation_count DESC);

-- Embeddings table
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    model_name VARCHAR(100) NOT NULL,
    vector_id VARCHAR(255), -- Reference to vector DB
    dimensions INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, model_name)
);

-- Clusters table
CREATE TABLE IF NOT EXISTS clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    name VARCHAR(255),
    description TEXT,
    algorithm VARCHAR(50) NOT NULL, -- 'leiden', 'louvain', 'hdbscan'
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
    name VARCHAR(255) NOT NULL,
    description TEXT,
    query TEXT,
    status VARCHAR(50) DEFAULT 'created', -- 'created', 'searching', 'clustering', 'outlining', 'writing', 'completed'
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Outlines table
CREATE TABLE IF NOT EXISTS outlines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    sections JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'approved', 'writing', 'completed'
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

-- Citations table
CREATE TABLE IF NOT EXISTS citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id UUID REFERENCES written_content(id) ON DELETE CASCADE,
    paper_id UUID REFERENCES papers(id) ON DELETE SET NULL,
    citation_text TEXT,
    citation_style VARCHAR(50) DEFAULT 'apa',
    location_in_text INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for foreign keys
CREATE INDEX idx_embeddings_paper_id ON embeddings(paper_id);
CREATE INDEX idx_cluster_assignments_cluster_id ON cluster_assignments(cluster_id);
CREATE INDEX idx_cluster_assignments_paper_id ON cluster_assignments(paper_id);
CREATE INDEX idx_outlines_project_id ON outlines(project_id);
CREATE INDEX idx_written_content_outline_id ON written_content(outline_id);
CREATE INDEX idx_citations_content_id ON citations(content_id);
CREATE INDEX idx_citations_paper_id ON citations(paper_id);

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

CREATE TRIGGER update_outlines_updated_at BEFORE UPDATE ON outlines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_written_content_updated_at BEFORE UPDATE ON written_content
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
