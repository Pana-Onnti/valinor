"""
Security test suite for Valinor SaaS (VAL-34).

Tests:
- Prompt injection attacks against each agent
- Cross-tenant isolation
- Adversarial SQL payloads
- Data exfiltration attempts

Run with:
    pytest security/ -v
"""
