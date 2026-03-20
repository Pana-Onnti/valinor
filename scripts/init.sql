-- Valinor SaaS Metadata Database Initialization
-- This script creates the metadata database and tables
-- NOTE: This does NOT store any client data, only metadata and audit trails

-- Create database if using PostgreSQL
-- CREATE DATABASE valinor_metadata;
-- \c valinor_metadata;

-- ═══ METADATA TABLES ═══

-- Analysis Jobs Table
-- Tracks job execution metadata
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    client_name TEXT NOT NULL, -- Client identifier (hashed if needed)
    period TEXT NOT NULL,
    config_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_job_id ON analysis_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_client_name ON analysis_jobs(client_name);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status ON analysis_jobs(status);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_created_at ON analysis_jobs(created_at);

-- Analysis Results Table
-- Stores aggregated results and metrics (no sensitive data)
CREATE TABLE IF NOT EXISTS analysis_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_id TEXT NOT NULL,
    findings_count INTEGER DEFAULT 0,
    critical_issues INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    opportunities INTEGER DEFAULT 0,
    execution_time_seconds INTEGER,
    success BOOLEAN DEFAULT false,
    error_type TEXT,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    FOREIGN KEY (job_id) REFERENCES analysis_jobs(job_id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_analysis_results_job_id ON analysis_results(job_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_completed_at ON analysis_results(completed_at);

-- Client Memory Table
-- Stores learning memory between analyses (aggregated data only)
CREATE TABLE IF NOT EXISTS client_memory (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_name TEXT NOT NULL,
    period TEXT NOT NULL,
    memory JSONB NOT NULL, -- Aggregated memory data (no sensitive info)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_client_memory_client_period ON client_memory(client_name, period);
CREATE INDEX IF NOT EXISTS idx_client_memory_created_at ON client_memory(created_at);

-- Audit Log Table (append-only)
-- Tracks all system events for compliance
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    event TEXT NOT NULL,
    job_id TEXT,
    client_name TEXT,
    user_id TEXT,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB, -- Additional event context
    
    -- No foreign keys - this is an append-only audit trail
    CONSTRAINT audit_log_event_check CHECK (event IN (
        'job_created', 'job_started', 'job_completed', 'job_failed',
        'api_call', 'auth_success', 'auth_failure',
        'data_export', 'config_change', 'system_error'
    ))
);

-- Indexes for audit queries
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event);
CREATE INDEX IF NOT EXISTS idx_audit_log_job_id ON audit_log(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_client_name ON audit_log(client_name);

-- System Configuration Table
-- Stores system-wide configuration
CREATE TABLE IF NOT EXISTS system_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_by TEXT
);

-- Insert default system configuration
INSERT INTO system_config (key, value, description) VALUES
    ('max_concurrent_jobs', '5', 'Maximum number of concurrent analysis jobs'),
    ('job_timeout_seconds', '3600', 'Default job timeout in seconds'),
    ('cleanup_after_hours', '24', 'Hours after which to cleanup job data'),
    ('retention_days', '90', 'Days to retain metadata'),
    ('api_rate_limit', '{"requests_per_minute": 60, "requests_per_hour": 1000}', 'API rate limiting configuration')
ON CONFLICT (key) DO NOTHING;

-- User Sessions Table (if auth is implemented)
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    active BOOLEAN DEFAULT true
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_sessions_session_id ON user_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

-- ═══ VIEWS FOR ANALYTICS ═══

-- Job Statistics View
CREATE OR REPLACE VIEW job_statistics AS
SELECT 
    client_name,
    COUNT(*) as total_jobs,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful_jobs,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs,
    AVG(CASE WHEN ar.execution_time_seconds IS NOT NULL THEN ar.execution_time_seconds END) as avg_execution_time,
    MAX(aj.created_at) as last_job_date,
    AVG(ar.findings_count) as avg_findings_count
FROM analysis_jobs aj
LEFT JOIN analysis_results ar ON aj.job_id = ar.job_id
GROUP BY client_name;

-- Daily Usage View
CREATE OR REPLACE VIEW daily_usage AS
SELECT 
    DATE(created_at) as date,
    COUNT(*) as total_jobs,
    COUNT(DISTINCT client_name) as unique_clients,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful_jobs,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs
FROM analysis_jobs
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- ═══ FUNCTIONS ═══

-- Function to clean up old data
CREATE OR REPLACE FUNCTION cleanup_old_metadata(retention_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Clean up old job data
    DELETE FROM analysis_jobs 
    WHERE created_at < NOW() - INTERVAL '1 day' * retention_days;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Clean up orphaned results (should be handled by CASCADE)
    DELETE FROM analysis_results 
    WHERE created_at < NOW() - INTERVAL '1 day' * retention_days
    AND job_id NOT IN (SELECT job_id FROM analysis_jobs);
    
    -- Clean up old memory (keep more recent for learning)
    DELETE FROM client_memory 
    WHERE created_at < NOW() - INTERVAL '1 day' * (retention_days * 2);
    
    -- Note: We keep audit logs longer for compliance
    -- Only clean if explicitly requested with longer retention
    IF retention_days > 365 THEN
        DELETE FROM audit_log 
        WHERE timestamp < NOW() - INTERVAL '1 day' * retention_days;
    END IF;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function to log audit events
CREATE OR REPLACE FUNCTION log_audit_event(
    p_event TEXT,
    p_job_id TEXT DEFAULT NULL,
    p_client_name TEXT DEFAULT NULL,
    p_user_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    audit_id UUID;
BEGIN
    INSERT INTO audit_log (event, job_id, client_name, user_id, metadata)
    VALUES (p_event, p_job_id, p_client_name, p_user_id, p_metadata)
    RETURNING id INTO audit_id;
    
    RETURN audit_id;
END;
$$ LANGUAGE plpgsql;

-- ═══ TRIGGERS ═══

-- Trigger to automatically log job state changes
CREATE OR REPLACE FUNCTION log_job_state_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM log_audit_event('job_created', NEW.job_id, NEW.client_name, NULL, 
            jsonb_build_object('period', NEW.period));
    ELSIF TG_OP = 'UPDATE' AND OLD.status != NEW.status THEN
        IF NEW.status = 'running' THEN
            PERFORM log_audit_event('job_started', NEW.job_id, NEW.client_name);
        ELSIF NEW.status = 'completed' THEN
            PERFORM log_audit_event('job_completed', NEW.job_id, NEW.client_name);
        ELSIF NEW.status = 'failed' THEN
            PERFORM log_audit_event('job_failed', NEW.job_id, NEW.client_name);
        END IF;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Apply the trigger
DROP TRIGGER IF EXISTS audit_job_changes ON analysis_jobs;
CREATE TRIGGER audit_job_changes
    AFTER INSERT OR UPDATE ON analysis_jobs
    FOR EACH ROW EXECUTE FUNCTION log_job_state_change();

-- ═══ PERMISSIONS & SECURITY ═══

-- Create application user (run separately with appropriate credentials)
-- CREATE USER valinor_app WITH PASSWORD 'secure_password_here';

-- Grant necessary permissions
-- GRANT CONNECT ON DATABASE valinor_metadata TO valinor_app;
-- GRANT USAGE ON SCHEMA public TO valinor_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO valinor_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO valinor_app;

-- Row Level Security (enable if needed for multi-tenancy)
-- ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE analysis_results ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE client_memory ENABLE ROW LEVEL SECURITY;

-- Example RLS policy (uncomment if using multi-tenancy)
-- CREATE POLICY analysis_jobs_tenant_isolation ON analysis_jobs
--     USING (client_name = current_setting('app.current_tenant', true));

-- ═══ INITIAL DATA ═══

-- Insert initial audit log entry
SELECT log_audit_event('system_initialized', NULL, NULL, 'system', 
    jsonb_build_object(
        'version', '1.0.0',
        'initialized_at', NOW(),
        'schema_version', '1.0'
    ));

-- Show completion message
DO $$
BEGIN
    RAISE NOTICE 'Valinor SaaS metadata database initialized successfully!';
    RAISE NOTICE 'Tables created: analysis_jobs, analysis_results, client_memory, audit_log, system_config, user_sessions';
    RAISE NOTICE 'Views created: job_statistics, daily_usage';
    RAISE NOTICE 'Functions created: cleanup_old_metadata, log_audit_event';
    RAISE NOTICE 'Remember to set up proper user permissions for production!';
END $$;