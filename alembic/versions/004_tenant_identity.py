"""Tenant identity: tenants + per-tenant API keys (additive foundation)

Revision ID: 004_tenant_identity
Revises: 003_uploaded_files
Create Date: 2026-06-03

Adds the `tenants` and `tenant_api_keys` tables and seeds the default tenant row
ONLY — no API key is baked in (operators register keys out of band via
scripts/register_tenant.py / scripts/seed_default_tenant.py), so no shared test
secret is ever committed.

This migration is ADDITIVE: it changes no existing behavior. The auth enforcement
that consumes these tables ships later and gated (VAL-174 A2). Single linear chain:
8400bc1a4be5 -> 002_multi_tenant_rls -> 003_uploaded_files -> 004_tenant_identity.

Refs: VAL-174
"""
from typing import Sequence, Union

from alembic import op

revision: str = '004_tenant_identity'
down_revision: Union[str, None] = '003_uploaded_files'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenants_is_active ON tenants(is_active);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            key_name VARCHAR(100) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            last_used_at TIMESTAMP,
            CONSTRAINT key_name_per_tenant UNIQUE (tenant_id, key_name)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_key_hash ON tenant_api_keys(key_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant_active ON tenant_api_keys(tenant_id, is_active);")

    # Seed the default tenant row ONLY — no API key (register out of band).
    op.execute(f"""
        INSERT INTO tenants (id, name, display_name, is_active)
        VALUES ('{_DEFAULT_TENANT_ID}', 'default-tenant', 'Default Tenant', true)
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_api_keys;")
    op.execute("DROP TABLE IF EXISTS tenants;")
