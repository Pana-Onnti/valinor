#!/usr/bin/env python3
"""Mint (or rotate) the default tenant's API key — e.g. for single-tenant prod.

The 004 migration seeds the default *tenant row* but NO key (so no secret is
committed). Run this once per environment to issue the default tenant's key.

Usage:
    python scripts/seed_default_tenant.py            # generate + print a new key
    python scripts/seed_default_tenant.py --key-hash <sha256>   # register a known hash

Refs: VAL-174
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shared.credentials import generate_api_key, hash_api_key  # noqa: E402

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_DB = "postgresql://postgres:postgres@localhost:5432/valinor_metadata"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed/rotate the default tenant API key")
    parser.add_argument("--key-hash", default=None, help="Register a known hash instead of generating a key")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    database_url = args.database_url or os.getenv("DATABASE_URL", _DEFAULT_DB)
    api_key = None
    if args.key_hash:
        key_hash = args.key_hash
    else:
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)

    try:
        engine = create_engine(database_url)
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM tenant_api_keys WHERE tenant_id = :t AND key_name = 'default-key'"),
                {"t": _DEFAULT_TENANT_ID},
            )
            conn.execute(
                text("INSERT INTO tenant_api_keys (tenant_id, key_hash, key_name, is_active) "
                     "VALUES (:t, :h, 'default-key', true)"),
                {"t": _DEFAULT_TENANT_ID, "h": key_hash},
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Default tenant key seeded.")
    if api_key:
        print(f"  API key (shown once): {api_key}")
    print(f"  key_hash: {key_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
