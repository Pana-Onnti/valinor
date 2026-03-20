-- Valinor SaaS Database Schema
-- Metadata storage only - no client data

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Clients table
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Analyses table
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reports table
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id),
    type VARCHAR(50) NOT NULL,
    title VARCHAR(255),
    content TEXT,
    file_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id),
    action VARCHAR(100) NOT NULL,
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_analyses_client_id ON analyses(client_id);
CREATE INDEX idx_analyses_status ON analyses(status);
CREATE INDEX idx_reports_analysis_id ON reports(analysis_id);
CREATE INDEX idx_audit_log_client_id ON audit_log(client_id);

-- Client profiles table (Client Memory Layer)
CREATE TABLE IF NOT EXISTS client_profiles (
    client_name TEXT PRIMARY KEY,
    profile     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_profiles_name ON client_profiles(client_name);

-- Extended analysis_jobs table with run_delta and profile snapshot
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS run_delta JSONB;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS client_profile_snapshot JSONB;
