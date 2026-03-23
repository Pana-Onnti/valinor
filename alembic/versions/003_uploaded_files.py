"""uploaded_files table with RLS for tenant isolation

Revision ID: 003_uploaded_files
Revises: 002_multi_tenant_rls
Create Date: 2026-03-22

Creates the uploaded_files table that tracks every CSV/Excel file uploaded
by tenant users.  Includes RLS policy for tenant isolation following the
same pattern as 002_multi_tenant_rls.

Refs: VAL-89
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '003_uploaded_files'
down_revision: Union[str, None] = '002_multi_tenant_rls'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create uploaded_files table
    op.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            client_name      VARCHAR(255) NOT NULL,
            original_filename VARCHAR(500) NOT NULL,
            stored_path      VARCHAR(1000) NOT NULL,
            file_size        BIGINT NOT NULL,
            file_type        VARCHAR(10) NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            uploaded_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
            processed_at     TIMESTAMP WITH TIME ZONE
        )
    """)

    # 2. Index for the most common query pattern: tenant + client lookups
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_tenant_client
        ON uploaded_files(tenant_id, client_name);
    """)

    # 3. Index on status for cleanup queries (find expired/pending)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_status
        ON uploaded_files(status);
    """)

    # 4. Index on uploaded_at for age-based cleanup
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at
        ON uploaded_files(uploaded_at DESC);
    """)

    # 5. Add CHECK constraint on file_type
    op.execute("""
        ALTER TABLE uploaded_files
        ADD CONSTRAINT chk_uploaded_files_file_type
        CHECK (file_type IN ('csv', 'xlsx', 'xls'));
    """)

    # 6. Add CHECK constraint on status
    op.execute("""
        ALTER TABLE uploaded_files
        ADD CONSTRAINT chk_uploaded_files_status
        CHECK (status IN ('pending', 'processed', 'error', 'expired'));
    """)

    # 7. Enable Row Level Security
    op.execute("ALTER TABLE uploaded_files ENABLE ROW LEVEL SECURITY;")

    # 8. RLS policy: SELECT — tenant must match current_setting
    op.execute("""
        CREATE POLICY tenant_isolation_select ON uploaded_files
        FOR SELECT
        USING (
            tenant_id = current_setting('app.current_tenant', true)::uuid
            OR current_setting('app.current_tenant', true) IS NULL
        );
    """)

    # 9. RLS policy: ALL (INSERT/UPDATE/DELETE) — tenant must match
    op.execute("""
        CREATE POLICY tenant_isolation_modify ON uploaded_files
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

    # 10. Grant access to the app role (created in 002_multi_tenant_rls)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'valinor_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON uploaded_files TO valinor_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_select ON uploaded_files;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_modify ON uploaded_files;")
    op.execute("ALTER TABLE uploaded_files DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_uploaded_files_uploaded_at;")
    op.execute("DROP INDEX IF EXISTS idx_uploaded_files_status;")
    op.execute("DROP INDEX IF EXISTS idx_uploaded_files_tenant_client;")
    op.execute("DROP TABLE IF EXISTS uploaded_files;")
