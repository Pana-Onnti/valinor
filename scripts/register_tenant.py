#!/usr/bin/env python3
"""Register a new tenant and mint its first API key.

Usage:
    python scripts/register_tenant.py --name acme --display-name 'ACME Corp'

Prints the generated API key ONCE (store it securely — only its hash is kept).

Refs: VAL-174
"""
import argparse
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shared.credentials import generate_api_key, hash_api_key  # noqa: E402

_DEFAULT_DB = "postgresql://postgres:postgres@localhost:5432/valinor_metadata"


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a new tenant + API key")
    parser.add_argument("--name", required=True, help="Unique tenant name (alphanumeric, -/_)")
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    if not args.name.replace("-", "").replace("_", "").isalnum():
        print(f"ERROR: name must be alphanumeric with -/_, got '{args.name}'", file=sys.stderr)
        return 1

    database_url = args.database_url or os.getenv("DATABASE_URL", _DEFAULT_DB)
    tenant_id = str(uuid.uuid4())
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    try:
        engine = create_engine(database_url)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name, display_name, is_active) "
                     "VALUES (:id, :name, :display_name, true)"),
                {"id": tenant_id, "name": args.name, "display_name": args.display_name or args.name},
            )
            conn.execute(
                text("INSERT INTO tenant_api_keys (tenant_id, key_hash, key_name, is_active) "
                     "VALUES (:tenant_id, :key_hash, :key_name, true)"),
                {"tenant_id": tenant_id, "key_hash": key_hash, "key_name": f"{args.name}-default"},
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\n=== Tenant registered ===")
    print(f"  tenant_id : {tenant_id}")
    print(f"  name      : {args.name}")
    print("\n  API key (shown once — store securely):")
    print(f"    {api_key}")
    print("\n  Use: Authorization: Bearer <key>\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
