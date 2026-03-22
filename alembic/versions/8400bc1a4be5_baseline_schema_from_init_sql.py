"""baseline schema from init.sql

Revision ID: 8400bc1a4be5
Revises: 
Create Date: 2026-03-22 16:09:33.975240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8400bc1a4be5'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extension
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # Clients table
    op.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Analyses table
    op.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            client_id UUID REFERENCES clients(id),
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Reports table
    op.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            analysis_id UUID REFERENCES analyses(id),
            type VARCHAR(50) NOT NULL,
            title VARCHAR(255),
            content TEXT,
            file_path VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Audit log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            client_id UUID REFERENCES clients(id),
            action VARCHAR(100) NOT NULL,
            details JSONB,
            ip_address VARCHAR(45),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes on core tables
    op.execute("CREATE INDEX IF NOT EXISTS idx_analyses_client_id ON analyses(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reports_analysis_id ON reports(analysis_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_client_id ON audit_log(client_id)")

    # Client profiles table (Client Memory Layer)
    op.execute("""
        CREATE TABLE IF NOT EXISTS client_profiles (
            client_name TEXT PRIMARY KEY,
            profile     JSONB NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Indexes on client_profiles
    op.execute("CREATE INDEX IF NOT EXISTS idx_client_profiles_name ON client_profiles(client_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_client_profiles_profile_gin ON client_profiles USING gin(profile)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_client_profiles_updated ON client_profiles(updated_at DESC)")

    # Extended columns on analyses
    op.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS run_delta JSONB")
    op.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS client_profile_snapshot JSONB")

    # Partial index for completed analyses
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyses_completed_at "
        "ON analyses(completed_at DESC) WHERE status = 'completed'"
    )


def downgrade() -> None:
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS idx_analyses_completed_at")
    op.execute("DROP INDEX IF EXISTS idx_client_profiles_updated")
    op.execute("DROP INDEX IF EXISTS idx_client_profiles_profile_gin")
    op.execute("DROP INDEX IF EXISTS idx_client_profiles_name")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_client_id")
    op.execute("DROP INDEX IF EXISTS idx_reports_analysis_id")
    op.execute("DROP INDEX IF EXISTS idx_analyses_status")
    op.execute("DROP INDEX IF EXISTS idx_analyses_client_id")

    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS client_profiles")
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS reports")
    op.execute("DROP TABLE IF EXISTS analyses")
    op.execute("DROP TABLE IF EXISTS clients")
