"""Tenant identity foundation (VAL-174 A1) — credential helpers + alembic chain.

Pure additive unit tests. The 004 migration itself is exercised against a live
Postgres only (needs_live_env); here we assert the migration files form a single
linear chain so a head collision (the adversarial-review finding) fails CI early.
"""
import re
from pathlib import Path

from shared.credentials import generate_api_key, hash_api_key, keys_match


class TestCredentialHelpers:
    def test_hash_is_deterministic_and_hex64(self):
        h1 = hash_api_key("vk_abc")
        h2 = hash_api_key("vk_abc")
        assert h1 == h2
        assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)

    def test_generate_format_and_uniqueness(self):
        k1 = generate_api_key()
        k2 = generate_api_key()
        assert k1.startswith("vk_") and len(k1) == 67  # 'vk_' + 64 hex
        assert k1 != k2  # random

    def test_keys_match_true_for_matching(self):
        key = generate_api_key()
        assert keys_match(key, hash_api_key(key)) is True

    def test_keys_match_false_for_mismatch(self):
        key = generate_api_key()
        assert keys_match(key, hash_api_key("vk_other")) is False
        assert keys_match("wrong", hash_api_key(key)) is False


class TestAlembicSingleHead:
    """Adversarial-review guard: exactly one head, no duplicate/colliding revisions."""

    def _revisions(self):
        versions = Path(__file__).parent.parent / "alembic" / "versions"
        rev_re = re.compile(r"^revision\s*[:=].*?['\"]([^'\"]+)['\"]", re.MULTILINE)
        down_re = re.compile(r"^down_revision\s*[:=].*?['\"]([^'\"]+)['\"]", re.MULTILINE)
        revs, downs = [], set()
        for f in versions.glob("*.py"):
            if f.name.startswith("__"):
                continue
            text = f.read_text(encoding="utf-8")
            m = rev_re.search(text)
            assert m, f"no revision id in {f.name}"
            revs.append(m.group(1))
            dm = down_re.search(text)
            if dm:
                downs.add(dm.group(1))
        return revs, downs

    def test_no_duplicate_revision_ids(self):
        revs, _ = self._revisions()
        assert len(revs) == len(set(revs)), f"duplicate revision ids: {revs}"

    def test_exactly_one_head(self):
        revs, downs = self._revisions()
        heads = [r for r in revs if r not in downs]
        assert len(heads) == 1, f"expected one alembic head, found {heads}"

    def test_004_chains_off_003(self):
        revs, downs = self._revisions()
        assert "004_tenant_identity" in revs
        assert "003_uploaded_files" in downs  # 004 builds on 003
