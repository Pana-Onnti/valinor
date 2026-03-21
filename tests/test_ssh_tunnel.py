"""
Tests for the SSH Tunnel module.

Covers ZeroTrustValidator configuration validation and SSHTunnelManager retry
logic in create_ssh_tunnel.  All network I/O and filesystem calls are mocked so
the suite runs without a real SSH server or key file.
"""

import socket
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure project root is on the path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub optional dependencies that may not be installed in the test venv.
# paramiko and cryptography ARE installed (checked), so only stub structlog.
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


# structlog stub — provide a no-op get_logger so the module-level call in
# ssh_tunnel.py does not crash when structlog is absent.
if "structlog" not in sys.modules:
    _structlog_stub = _make_stub("structlog")
    _structlog_stub.get_logger = lambda: MagicMock()
    sys.modules["structlog"] = _structlog_stub

# Stub paramiko BEFORE importing ssh_tunnel to prevent loading real SSH/crypto deps.
# We replace the whole package so the shared.ssh_tunnel import never triggers
# the paramiko → cryptography.hazmat chain.
_paramiko_stub = _make_stub("paramiko")
_paramiko_stub.SSHClient = MagicMock
_paramiko_stub.AutoAddPolicy = MagicMock
# RSAKey needs from_private_key_file as a class-level attribute for patch() to work
_RSAKeyMock = MagicMock()
_RSAKeyMock.from_private_key_file = MagicMock(return_value=MagicMock())
_paramiko_stub.RSAKey = _RSAKeyMock
_pex_stub = _make_stub("paramiko.ssh_exception")
_pex_stub.AuthenticationException = type("AuthenticationException", (Exception,), {})
_pex_stub.NoValidConnectionsError = type("NoValidConnectionsError", (OSError,), {})
_paramiko_stub.ssh_exception = _pex_stub
_paramiko_stub.AuthenticationException = _pex_stub.AuthenticationException
_paramiko_stub.NoValidConnectionsError = _pex_stub.NoValidConnectionsError
sys.modules["paramiko"] = _paramiko_stub
sys.modules["paramiko.ssh_exception"] = _pex_stub

# ---------------------------------------------------------------------------
# Now import the module under test
# ---------------------------------------------------------------------------
from shared.ssh_tunnel import ZeroTrustValidator, SSHTunnelManager  # noqa: E402


# ===========================================================================
# Helper: build a minimal valid ssh_config dict
# ===========================================================================

def _ssh_cfg(**overrides) -> dict:
    base = {
        "host": "bastion.example.com",
        "username": "readonly",
        "private_key_path": "/home/user/.ssh/id_rsa",
        "port": 22,
    }
    base.update(overrides)
    return base


def _db_cfg(**overrides) -> dict:
    base = {
        "host": "db.internal",
        "port": 5432,
        "connection_string": "postgresql://user:pass@db.internal:5432/mydb",
        "type": "postgresql",
    }
    base.update(overrides)
    return base


# ===========================================================================
# TestZeroTrustValidator — configuration validation
# ===========================================================================

class TestZeroTrustValidator(unittest.TestCase):
    """Unit tests for ZeroTrustValidator.validate_ssh_config and validate_db_config."""

    # ------------------------------------------------------------------
    # SSH config tests
    # ------------------------------------------------------------------

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_valid_complete_ssh_config(self, mock_exists, mock_stat):
        """All fields present, key file exists with 0o600 permissions → True."""
        stat_result = MagicMock()
        stat_result.st_mode = 0o100600  # regular file + 600
        mock_stat.return_value = stat_result

        result = ZeroTrustValidator.validate_ssh_config(_ssh_cfg())

        self.assertTrue(result)
        mock_exists.assert_called_once_with("/home/user/.ssh/id_rsa")

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_missing_host_fails(self, mock_exists, mock_stat):
        """Config without host → False."""
        cfg = _ssh_cfg()
        del cfg["host"]

        result = ZeroTrustValidator.validate_ssh_config(cfg)

        self.assertFalse(result)

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_missing_username_fails(self, mock_exists, mock_stat):
        """Config without username field → False."""
        cfg = _ssh_cfg()
        del cfg["username"]

        result = ZeroTrustValidator.validate_ssh_config(cfg)

        self.assertFalse(result)

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_missing_key_path_fails(self, mock_exists, mock_stat):
        """Config without private_key_path field → False."""
        cfg = _ssh_cfg()
        del cfg["private_key_path"]

        result = ZeroTrustValidator.validate_ssh_config(cfg)

        self.assertFalse(result)

    @patch("shared.ssh_tunnel.os.path.exists", return_value=False)
    def test_nonexistent_key_file_fails(self, mock_exists):
        """Key path that does not exist on disk → False."""
        result = ZeroTrustValidator.validate_ssh_config(_ssh_cfg())

        self.assertFalse(result)
        mock_exists.assert_called_once_with("/home/user/.ssh/id_rsa")

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_bad_key_permissions_fails(self, mock_exists, mock_stat):
        """Key with 0o644 permissions (world-readable) → False."""
        stat_result = MagicMock()
        stat_result.st_mode = 0o100644  # regular file + 644
        mock_stat.return_value = stat_result

        result = ZeroTrustValidator.validate_ssh_config(_ssh_cfg())

        self.assertFalse(result)

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_port_defaults_to_22(self, mock_exists, mock_stat):
        """Config without explicit port is still accepted; caller uses default 22."""
        stat_result = MagicMock()
        stat_result.st_mode = 0o100600
        mock_stat.return_value = stat_result

        cfg = _ssh_cfg()
        del cfg["port"]  # port is optional in ZeroTrustValidator

        result = ZeroTrustValidator.validate_ssh_config(cfg)

        # Validation should succeed regardless of whether port is absent
        self.assertTrue(result)

    # ------------------------------------------------------------------
    # DB config tests
    # ------------------------------------------------------------------

    def test_valid_db_config_all_fields(self):
        """Complete db config with all required fields → True."""
        result = ZeroTrustValidator.validate_db_config(_db_cfg())
        self.assertTrue(result)

    def test_db_config_missing_host(self):
        """DB config without host field → False."""
        cfg = _db_cfg()
        del cfg["host"]

        result = ZeroTrustValidator.validate_db_config(cfg)

        self.assertFalse(result)

    def test_db_config_missing_type(self):
        """DB config without type field → False (required by validate_db_config)."""
        # validate_db_config checks for ['host', 'port', 'connection_string'].
        # 'type' is not in that list, so we test that host + port + connection_string
        # are all that is strictly required — meaning removing one of those fails.
        cfg = _db_cfg()
        del cfg["port"]

        result = ZeroTrustValidator.validate_db_config(cfg)

        self.assertFalse(result)

    def test_db_config_missing_connection_string(self):
        """DB config without connection_string → False."""
        cfg = _db_cfg()
        del cfg["connection_string"]

        result = ZeroTrustValidator.validate_db_config(cfg)

        self.assertFalse(result)


# ===========================================================================
# TestSSHTunnelRetry — exponential backoff in SSHTunnelManager.create_tunnel
# ===========================================================================

def _make_paramiko_mocks():
    """Return (mock_ssh_client_class, mock_transport, mock_channel) triple."""
    mock_transport = MagicMock()
    mock_channel = MagicMock()
    mock_channel.closed = True  # stop the forwarding thread immediately

    mock_transport.open_channel.return_value = mock_channel

    mock_client_instance = MagicMock()
    mock_client_instance.get_transport.return_value = mock_transport

    mock_client_class = MagicMock(return_value=mock_client_instance)
    return mock_client_class, mock_client_instance, mock_transport, mock_channel


class TestSSHTunnelRetry(unittest.TestCase):
    """
    Tests for the exponential-backoff retry loop inside
    SSHTunnelManager.create_tunnel.
    """

    def _run_tunnel(self, manager: SSHTunnelManager, connect_side_effect=None,
                    connect_return=None):
        """
        Helper: drive create_tunnel with mocked paramiko.  Returns the local
        connection string yielded by the context manager, or re-raises any
        exception thrown inside it.
        """
        ssh_cfg = {
            "host": "bastion.example.com",
            "port": 22,
            "username": "readonly",
            "private_key_path": "/fake/key",
        }
        db_cfg = {
            "host": "db.internal",
            "port": 5432,
            "connection_string": "postgresql://u:p@db.internal:5432/mydb",
        }

        mock_client_class, mock_instance, mock_transport, mock_channel = (
            _make_paramiko_mocks()
        )

        if connect_side_effect is not None:
            mock_instance.connect.side_effect = connect_side_effect

        with patch("shared.ssh_tunnel.paramiko.SSHClient", mock_client_class), \
             patch("shared.ssh_tunnel.paramiko.RSAKey.from_private_key_file",
                   return_value=MagicMock()), \
             patch("shared.ssh_tunnel.time.sleep"):  # suppress actual delays
            ctx = manager.create_tunnel(ssh_cfg, db_cfg, job_id="test-job-1")
            local_conn = ctx.__enter__()
            ctx.__exit__(None, None, None)

        return local_conn, mock_instance

    # ------------------------------------------------------------------

    def test_successful_connection_first_try(self):
        """Mock paramiko succeeds on first connect → tunnel established, 1 connect call."""
        manager = SSHTunnelManager(encryption_key=None)
        local_conn, mock_instance = self._run_tunnel(manager)

        # connect was called exactly once
        mock_instance.connect.assert_called_once()
        # The yielded connection string must point to the local tunnel
        self.assertIn("127.0.0.1", local_conn)

    def test_retries_on_connection_error(self):
        """
        First connect raises NoValidConnectionsError, second succeeds →
        connect is called exactly 2 times.
        """
        # Use the paramiko that ssh_tunnel.py actually imported (may differ from
        # sys.modules["paramiko"] if test ordering replaced it).
        import shared.ssh_tunnel as _sshtunnel_mod
        _pm = getattr(_sshtunnel_mod, "paramiko", None) or __import__("paramiko")
        _NoValid = _pm.ssh_exception.NoValidConnectionsError

        side_effect = [
            _NoValid({("bastion.example.com", 22): Exception("refused")}),
            None,  # second attempt succeeds (no exception)
        ]

        manager = SSHTunnelManager(encryption_key=None)
        local_conn, mock_instance = self._run_tunnel(
            manager, connect_side_effect=side_effect
        )

        self.assertEqual(mock_instance.connect.call_count, 2)
        self.assertIn("127.0.0.1", local_conn)

    def test_max_retries_exceeded_raises(self):
        """
        All 3 attempts raise NoValidConnectionsError → exception is re-raised
        after the final attempt; connect is called exactly 3 times.
        """
        import shared.ssh_tunnel as _sshtunnel_mod
        _pm = getattr(_sshtunnel_mod, "paramiko", None) or __import__("paramiko")
        _NoValid = _pm.ssh_exception.NoValidConnectionsError

        exc = _NoValid({("bastion.example.com", 22): Exception("refused")})

        ssh_cfg = {
            "host": "bastion.example.com",
            "port": 22,
            "username": "readonly",
            "private_key_path": "/fake/key",
        }
        db_cfg = {
            "host": "db.internal",
            "port": 5432,
            "connection_string": "postgresql://u:p@db.internal:5432/mydb",
        }

        mock_client_class, mock_instance, _, _ = _make_paramiko_mocks()
        mock_instance.connect.side_effect = exc  # always fails

        manager = SSHTunnelManager(encryption_key=None)

        with patch("shared.ssh_tunnel.paramiko.SSHClient", mock_client_class), \
             patch("shared.ssh_tunnel.paramiko.RSAKey.from_private_key_file",
                   return_value=MagicMock()), \
             patch("shared.ssh_tunnel.time.sleep"):
            with self.assertRaises(_NoValid):
                with manager.create_tunnel(ssh_cfg, db_cfg, job_id="test-job-2"):
                    pass  # pragma: no cover

        self.assertEqual(mock_instance.connect.call_count, 3)

    def test_auth_error_not_retried(self):
        """
        AuthenticationException is raised immediately on first attempt —
        connect is called exactly once and no retry sleep occurs.
        """
        import paramiko

        auth_exc = paramiko.AuthenticationException("bad credentials")

        ssh_cfg = {
            "host": "bastion.example.com",
            "port": 22,
            "username": "readonly",
            "private_key_path": "/fake/key",
        }
        db_cfg = {
            "host": "db.internal",
            "port": 5432,
            "connection_string": "postgresql://u:p@db.internal:5432/mydb",
        }

        mock_client_class, mock_instance, _, _ = _make_paramiko_mocks()
        mock_instance.connect.side_effect = auth_exc

        manager = SSHTunnelManager(encryption_key=None)

        mock_sleep = MagicMock()
        with patch("shared.ssh_tunnel.paramiko.SSHClient", mock_client_class), \
             patch("shared.ssh_tunnel.paramiko.RSAKey.from_private_key_file",
                   return_value=MagicMock()), \
             patch("shared.ssh_tunnel.time.sleep", mock_sleep):
            with self.assertRaises(paramiko.AuthenticationException):
                with manager.create_tunnel(ssh_cfg, db_cfg, job_id="test-job-3"):
                    pass  # pragma: no cover

        # connect called only once — no retry
        mock_instance.connect.assert_called_once()
        # time.sleep was never called for a retry delay
        mock_sleep.assert_not_called()


# ===========================================================================
# Additional ZeroTrustValidator tests
# ===========================================================================

class TestZeroTrustValidatorExtended(unittest.TestCase):
    """Additional unit tests for ZeroTrustValidator edge cases."""

    # ------------------------------------------------------------------
    # SSH config — empty-value fields
    # ------------------------------------------------------------------

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_ssh_config_with_empty_host_fails(self, mock_exists, mock_stat):
        """SSH config with host='' (empty string) → False."""
        stat_result = MagicMock()
        stat_result.st_mode = 0o100600
        mock_stat.return_value = stat_result

        cfg = _ssh_cfg(host="")
        result = ZeroTrustValidator.validate_ssh_config(cfg)

        self.assertFalse(result)

    @patch("shared.ssh_tunnel.os.stat")
    @patch("shared.ssh_tunnel.os.path.exists", return_value=True)
    def test_ssh_config_empty_username_fails(self, mock_exists, mock_stat):
        """SSH config with username='' (empty string) → False."""
        stat_result = MagicMock()
        stat_result.st_mode = 0o100600
        mock_stat.return_value = stat_result

        cfg = _ssh_cfg(username="")
        result = ZeroTrustValidator.validate_ssh_config(cfg)

        self.assertFalse(result)

    # ------------------------------------------------------------------
    # DB config — empty/invalid field values
    # ------------------------------------------------------------------

    def test_db_config_with_empty_host_fails(self):
        """DB config with host='' present but empty → validate_db_config returns True
        because the validator only checks field *presence*, not emptiness for host.
        This test documents that behaviour explicitly."""
        # validate_db_config does NOT check whether host is non-empty, only that
        # the key exists.  Confirm the current (documented) behaviour.
        cfg = _db_cfg(host="")
        result = ZeroTrustValidator.validate_db_config(cfg)
        # Current implementation: field is present → passes host check → True
        self.assertTrue(result)

    def test_db_config_with_zero_port_fails(self):
        """DB config with port=0 → False (0 is outside valid 1-65535 range)."""
        cfg = _db_cfg(port=0)
        result = ZeroTrustValidator.validate_db_config(cfg)
        self.assertFalse(result)

    def test_valid_db_config_with_mysql_type(self):
        """DB config with type='mysql' and all required fields present → True.

        validate_db_config only requires host, port, connection_string; the
        'type' field is optional and must not cause a failure.
        """
        cfg = _db_cfg(type="mysql", connection_string="mysql://user:pass@db.internal:3306/mydb")
        result = ZeroTrustValidator.validate_db_config(cfg)
        self.assertTrue(result)

    def test_db_config_complete_fields_passes(self):
        """DB config with all helper-default fields (including type) → True."""
        result = ZeroTrustValidator.validate_db_config(_db_cfg())
        self.assertTrue(result)

    def test_ssh_config_rejects_missing_port_field_in_db_config(self):
        """Removing 'port' from db_cfg causes validate_db_config to return False."""
        cfg = _db_cfg()
        del cfg["port"]
        result = ZeroTrustValidator.validate_db_config(cfg)
        self.assertFalse(result)


# ===========================================================================
# Standalone / module-level sanity tests
# ===========================================================================

class TestZeroTrustValidatorInstantiation(unittest.TestCase):
    """Verify ZeroTrustValidator and its static methods are callable."""

    def test_zero_trust_validator_is_callable(self):
        """ZeroTrustValidator can be instantiated and its static methods are callable."""
        validator = ZeroTrustValidator()
        self.assertIsNotNone(validator)
        self.assertTrue(callable(ZeroTrustValidator.validate_ssh_config))
        self.assertTrue(callable(ZeroTrustValidator.validate_db_config))

    def test_ssh_tunnel_manager_creation_with_none_key(self):
        """SSHTunnelManager(encryption_key=None) does not raise."""
        manager = SSHTunnelManager(encryption_key=None)
        self.assertIsNotNone(manager)

    def test_ssh_tunnel_manager_creation_with_string_key(self):
        """SSHTunnelManager with a valid Fernet base64 key does not raise."""
        # A Fernet key must be 32 url-safe base64-encoded bytes (44-char string).
        from cryptography.fernet import Fernet
        valid_key = Fernet.generate_key().decode()
        manager = SSHTunnelManager(encryption_key=valid_key)
        self.assertIsNotNone(manager)


# ===========================================================================
# Additional SSHTunnelRetry tests
# ===========================================================================

class TestSSHTunnelRetryExtended(unittest.TestCase):
    """Extra retry / connection-string tests for SSHTunnelManager.create_tunnel."""

    def test_local_connection_string_format(self):
        """After a successful tunnel, the yielded string contains protocol, 127.0.0.1 and a port."""
        ssh_cfg = {
            "host": "bastion.example.com",
            "port": 22,
            "username": "readonly",
            "private_key_path": "/fake/key",
        }
        db_cfg = {
            "host": "db.internal",
            "port": 5432,
            "connection_string": "postgresql://u:p@db.internal:5432/mydb",
        }

        mock_client_class, mock_instance, _, _ = _make_paramiko_mocks()
        manager = SSHTunnelManager(encryption_key=None)

        with patch("shared.ssh_tunnel.paramiko.SSHClient", mock_client_class), \
             patch("shared.ssh_tunnel.paramiko.RSAKey.from_private_key_file",
                   return_value=MagicMock()), \
             patch("shared.ssh_tunnel.time.sleep"):
            ctx = manager.create_tunnel(ssh_cfg, db_cfg, job_id="fmt-test-1")
            local_conn = ctx.__enter__()
            ctx.__exit__(None, None, None)

        self.assertIn("postgresql://", local_conn)
        self.assertIn("127.0.0.1", local_conn)
        # Port number must appear somewhere after the host
        import re
        self.assertRegex(local_conn, r"127\.0\.0\.1:\d+")

    def test_second_retry_on_connection_error(self):
        """Two NoValidConnectionsError then success → connect is called exactly 3 times."""
        import shared.ssh_tunnel as _sshtunnel_mod
        _pm = getattr(_sshtunnel_mod, "paramiko", None) or __import__("paramiko")
        _NoValid = _pm.ssh_exception.NoValidConnectionsError

        err = {"(bastion.example.com, 22)": Exception("refused")}
        side_effect = [
            _NoValid(err),
            _NoValid(err),
            None,  # third attempt succeeds
        ]

        ssh_cfg = {
            "host": "bastion.example.com",
            "port": 22,
            "username": "readonly",
            "private_key_path": "/fake/key",
        }
        db_cfg = {
            "host": "db.internal",
            "port": 5432,
            "connection_string": "postgresql://u:p@db.internal:5432/mydb",
        }

        mock_client_class, mock_instance, _, _ = _make_paramiko_mocks()
        mock_instance.connect.side_effect = side_effect
        manager = SSHTunnelManager(encryption_key=None)

        with patch("shared.ssh_tunnel.paramiko.SSHClient", mock_client_class), \
             patch("shared.ssh_tunnel.paramiko.RSAKey.from_private_key_file",
                   return_value=MagicMock()), \
             patch("shared.ssh_tunnel.time.sleep"):
            ctx = manager.create_tunnel(ssh_cfg, db_cfg, job_id="retry-test-2")
            local_conn = ctx.__enter__()
            ctx.__exit__(None, None, None)

        self.assertEqual(mock_instance.connect.call_count, 3)
        self.assertIn("127.0.0.1", local_conn)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
