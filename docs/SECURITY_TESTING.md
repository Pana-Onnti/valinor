# Security Testing — Valinor SaaS

This document describes the security test suite implemented in `security/` (VAL-34).

## Overview

The Valinor swarm processes sensitive financial data from client databases.
The security test suite (red-teaming) verifies that:
1. Prompt injection attacks are mitigated
2. Cross-tenant data isolation is enforced
3. SQL safety guardrails prevent unauthorized operations
4. Write operations are never executed

## Running security tests

```bash
# Run only security tests
pytest security/ -v

# Run all tests (functional + security)
pytest tests/ security/ -v
```

## Test files

| File | Tests | Description |
|------|-------|-------------|
| `security/test_prompt_injection.py` | 30+ | SQL safety, injection payload detection, NL query validation |
| `security/test_tenant_isolation.py` | 10+ | Cross-tenant SQL isolation, adapter scoping |
| `security/adversarial_inputs.py` | — | Payload library (12 injection, 8 isolation, 10 SQL safety cases) |

## Attack vectors covered

### 1. Prompt Injection (PI-001 to PI-012)

| ID | Category | Description |
|----|----------|-------------|
| PI-001 | Direct | System prompt extraction via "Ignore previous instructions" |
| PI-002 | Direct | Role override ("You are DAN") |
| PI-003 | Direct | Instruction termination attack |
| PI-004 | Data-embedded | SQL injection via customer name field |
| PI-005 | Data-embedded | LLM instruction in invoice description |
| PI-006 | Data-embedded | XSS via product name |
| PI-007 | Jailbreak | Hypothetical framing |
| PI-008 | Jailbreak | Token smuggling via encoding |
| PI-009 | Jailbreak | Repetition coercion |
| PI-010 | SQL injection | UNION-based via NL question |
| PI-011 | SQL injection | Time-based injection (pg_sleep) |
| PI-012 | SQL injection | Comment-based injection |

### 2. Cross-Tenant Isolation (TI-001 to TI-008)

| ID | Category | Description |
|----|----------|-------------|
| TI-001 | Tenant bypass | Request data for explicit other tenant |
| TI-002 | Tenant bypass | Wildcard tenant access |
| TI-003 | Tenant bypass | Admin escalation via question |
| TI-004 | Tenant bypass | Null tenant bypass |
| TI-005 | Data leakage | Indirect cross-tenant aggregation |
| TI-006 | Data leakage | Subquery cross-tenant access |
| TI-007 | Privilege escalation | Write access request |
| TI-008 | Privilege escalation | Schema change request |

### 3. SQL Safety (SS-001 to SS-010)

All DML (DELETE, UPDATE, INSERT) and DDL (DROP, TRUNCATE, CREATE, ALTER) statements
are blocked at the connector layer (`DeltaConnector._require_select()`).

Dangerous functions detected: pg_read_file, pg_sleep, dblink, lo_import/lo_export.
Sensitive tables detected: pg_shadow, pg_authid, pg_user, pg_roles.

## Primary security controls

1. **Connector layer** (`shared/connectors/base.py`): `_require_select()` rejects
   any non-SELECT statement before it reaches the database.

2. **Tenant filters in entity_map**: The Cartographer sets `base_filter` per entity,
   which is injected into every generated query by `query_builder.build_queries()`.

3. **NL query input validation**: Pydantic validates question length (3–500 chars)
   and tenant_id is a required field.

4. **Per-tenant adapter isolation**: Each `tenant_id` gets its own `VannaAdapter`
   instance, preventing state leakage between tenants.

## Known limitations

- Prompt injection via malicious LLM-generated SQL is NOT fully tested (requires
  real LLM calls). The safety checker (`is_safe_sql`) provides a last-resort check.
- The Vanna NL→SQL adapter does not validate that generated SQL is scoped to the
  requesting tenant. Manual entity_map training with correct base_filter is required.

## Recommended next steps

1. Add integration tests with real (sandboxed) LLM calls for prompt injection
2. Implement SQL AST-based validation (not just string matching)
3. Add rate limiting per tenant to prevent enumeration attacks
4. Implement audit logging for all NL queries
