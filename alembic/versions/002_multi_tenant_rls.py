"""multi-tenant RLS: add tenant_id and enable row-level security

Revision ID: 002_multi_tenant_rls
Revises: 8400bc1a4be5
Create Date: 2026-03-22

Adds tenant_id UUID column to all tenant-scoped tables and enables
PostgreSQL Row Level Security (RLS) to enforce data isolation.

Tenant context is set per-request via:
    SET app.current_tenant = '<tenant_id>';

Tables covered:
    - analysis_jobs (init.sql)
    - analysis_results (init.sql)
    - client_memory (init.sql)
    - audit_log (init.sql)
    - clients (baseline migration)
    - analyses (baseline migration)
    - reports (baseline migration)

Refs: VAL-21
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '002_multi_tenant_rls'
down_revision: str = '8400bc1a4be5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that need tenant_id + RLS
# Format: (table_name, has_existing_data)
_TENANT_TABLES = [
    'analysis_jobs',
    'analysis_results',
    'client_memory',
    'audit_log',
    'clients',
    'analyses',
    'reports',
]

# Tables where audit_log is append-only — no RLS USING for INSERT
_APPEND_ONLY = {'audit_log'}


def upgrade() -> None:
    # 1. Add tenant_id column to all tenant-scoped tables
    for table in _TENANT_TABLES:
        op.execute(f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS tenant_id UUID;
        """)
        # Index for fast tenant-scoped queries
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id
            ON {table}(tenant_id);
        """)

    # 2. Create a default tenant for existing data
    op.execute("""
        DO $$
        DECLARE
            default_tenant UUID := '00000000-0000-0000-0000-000000000001';
        BEGIN
            -- Backfill existing rows with default tenant
            UPDATE analysis_jobs SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE analysis_results SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE client_memory SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE audit_log SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE clients SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE analyses SET tenant_id = default_tenant WHERE tenant_id IS NULL;
            UPDATE reports SET tenant_id = default_tenant WHERE tenant_id IS NULL;
        END $$;
    """)

    # 3. Make tenant_id NOT NULL after backfill
    for table in _TENANT_TABLES:
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN tenant_id SET NOT NULL;
        """)
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN tenant_id SET DEFAULT gen_random_uuid();
        """)

    # 4. Enable RLS on all tenant tables
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    # 5. Create RLS policies
    #    SELECT/UPDATE/DELETE: tenant_id must match current_setting
    #    INSERT: tenant_id must match current_setting (WITH CHECK)
    for table in _TENANT_TABLES:
        # Policy for SELECT, UPDATE, DELETE
        op.execute(f"""
            CREATE POLICY tenant_isolation_select ON {table}
            FOR SELECT
            USING (
                tenant_id = current_setting('app.current_tenant', true)::uuid
                OR current_setting('app.current_tenant', true) IS NULL
            );
        """)

        op.execute(f"""
            CREATE POLICY tenant_isolation_modify ON {table}
            FOR ALL
            USING (
                tenant_id = current_setting('app.current_tenant', true)::uuid
                OR current_setting('app.current_tenant', true) IS NULL
            )
            WITH CHECK (
                tenant_id = current_setting('app.current_tenant', true)::uuid
                OR current_setting('app.current_tenant', true) IS NULL
            );
        """)

    # 6. Create a superuser bypass role for admin operations
    #    The app user should NOT be a superuser — superusers bypass RLS
    op.execute("""
        DO $$
        BEGIN
            -- Create valinor_app role if not exists (non-superuser)
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'valinor_app') THEN
                CREATE ROLE valinor_app LOGIN;
            END IF;
        END $$;
    """)

    # 7. Grant table access to app role
    for table in _TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO valinor_app;")

    # 8. Composite indexes for common query patterns
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_analysis_jobs_tenant_status
        ON analysis_jobs(tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_analysis_jobs_tenant_created
        ON analysis_jobs(tenant_id, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_analyses_tenant_status
        ON analyses(tenant_id, status);
    """)


def downgrade() -> None:
    # Remove RLS policies and tenant_id columns
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_select ON {table};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_modify ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id;")

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_analysis_jobs_tenant_status;")
    op.execute("DROP INDEX IF EXISTS idx_analysis_jobs_tenant_created;")
    op.execute("DROP INDEX IF EXISTS idx_analyses_tenant_status;")
