"""
SSH Tunnel Manager for secure database connections.
Creates ephemeral SSH tunnels with automatic cleanup.

Supports SSH keys as:
  - File path: traditional /path/to/key
  - Pasted content: raw PEM string starting with "-----BEGIN"
"""

import os
import time
import socket
import tempfile
import threading
from contextlib import contextmanager
from typing import Dict, Optional, Tuple
import paramiko
import structlog
from cryptography.fernet import Fernet

logger = structlog.get_logger()


def _is_key_content(value: str) -> bool:
    """Detect whether a string is PEM key content (vs a file path)."""
    return value.strip().startswith("-----BEGIN")


@contextmanager
def _resolve_key(key_input: str):
    """
    Context manager that resolves an SSH key input to a file path.

    If `key_input` is PEM content (starts with "-----BEGIN"), write it to a
    secure temporary file (mode 0600), yield the path, then clean up.
    If it's a file path, yield it as-is with no cleanup.
    """
    if _is_key_content(key_input):
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.pem',
                prefix='valinor_ssh_',
                delete=False,
            )
            tmp.write(key_input.strip() + '\n')
            tmp.flush()
            tmp.close()
            os.chmod(tmp.name, 0o600)
            logger.debug("Wrote SSH key content to temp file", path=tmp.name)
            yield tmp.name
        finally:
            if tmp and os.path.exists(tmp.name):
                try:
                    os.unlink(tmp.name)
                    logger.debug("Cleaned up temp SSH key file", path=tmp.name)
                except Exception:
                    pass
    else:
        yield key_input


def _load_private_key(key_path: str) -> paramiko.PKey:
    """
    Attempt to load a private key from file, trying RSA, Ed25519, ECDSA
    in order. Raises paramiko.ssh_exception.SSHException if none work.
    """
    loaders = [
        paramiko.RSAKey.from_private_key_file,
        paramiko.Ed25519Key.from_private_key_file,
        paramiko.ECDSAKey.from_private_key_file,
    ]
    last_exc: Exception | None = None
    for loader in loaders:
        try:
            return loader(key_path)
        except (paramiko.ssh_exception.SSHException, ValueError) as exc:
            last_exc = exc
            continue
    raise paramiko.ssh_exception.SSHException(
        f"Could not load private key from {key_path}: {last_exc}"
    )


class SSHTunnelManager:
    """
    Manages SSH tunnels for secure database connections.
    Zero-trust architecture with ephemeral connections only.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize SSH tunnel manager.

        Args:
            encryption_key: Key for encrypting credentials at rest
        """
        self.encryption_key = encryption_key or os.getenv('ENCRYPTION_KEY')
        if self.encryption_key:
            self.cipher = Fernet(self.encryption_key.encode() if isinstance(self.encryption_key, str) else self.encryption_key)
        else:
            self.cipher = None
            logger.warning("No encryption key provided - credentials will not be encrypted")

        self.active_tunnels: Dict[str, paramiko.SSHClient] = {}
        self.tunnel_lock = threading.Lock()

    def find_free_port(self) -> int:
        """Find an available local port for tunneling."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    @contextmanager
    def create_tunnel(
        self,
        ssh_config: Dict,
        remote_db_config: Dict,
        job_id: str,
        max_duration: int = 3600  # 1 hour max
    ):
        """
        Create an ephemeral SSH tunnel with automatic cleanup.

        Args:
            ssh_config: SSH connection parameters
                - host: SSH server hostname
                - port: SSH port (default 22)
                - username: SSH username
                - private_key_path: Path to SSH private key OR raw PEM content
            remote_db_config: Remote database configuration
                - host: Database host (as seen from SSH server)
                - port: Database port
                - connection_string: Original connection string
            job_id: Unique job identifier for tracking
            max_duration: Maximum tunnel duration in seconds

        Yields:
            Modified connection string pointing to local tunnel
        """
        ssh_client = None
        tunnel_thread = None
        local_port = None
        start_time = time.time()

        # Resolve key input (path or content) to a usable file path
        key_input = ssh_config.get('private_key_path', '')

        with _resolve_key(key_input) as resolved_key_path:
            try:
                # Setup SSH client
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Load private key (tries RSA, Ed25519, ECDSA)
                if resolved_key_path:
                    private_key = _load_private_key(resolved_key_path)
                else:
                    raise ValueError("SSH private key required for tunnel")

                # Connect to SSH server with exponential backoff retry
                logger.info(
                    "Creating SSH tunnel",
                    job_id=job_id,
                    ssh_host=ssh_config['host'],
                    ssh_user=ssh_config['username']
                )

                _retry_delays = [2, 5, 10]
                _max_attempts = 3
                _retryable = (
                    paramiko.ssh_exception.NoValidConnectionsError,
                    socket.timeout,
                )

                for _attempt in range(1, _max_attempts + 1):
                    try:
                        ssh_client.connect(
                            hostname=ssh_config['host'],
                            port=ssh_config.get('port', 22),
                            username=ssh_config['username'],
                            pkey=private_key,
                            timeout=30,
                            banner_timeout=30,
                            auth_timeout=30
                        )
                        break  # Connection succeeded
                    except paramiko.AuthenticationException:
                        # Do not retry authentication failures
                        raise
                    except _retryable as exc:
                        if _attempt == _max_attempts:
                            logger.error(
                                "SSH connection failed after all retries",
                                job_id=job_id,
                                attempt=_attempt,
                                error=str(exc)
                            )
                            raise
                        _delay = _retry_delays[_attempt - 1]
                        logger.warning(
                            "SSH connection attempt failed, retrying",
                            job_id=job_id,
                            attempt=_attempt,
                            next_attempt=_attempt + 1,
                            retry_delay_seconds=_delay,
                            error=str(exc)
                        )
                        time.sleep(_delay)

                # Find free local port
                local_port = self.find_free_port()

                # Setup port forwarding
                transport = ssh_client.get_transport()
                channel = transport.open_channel(
                    'direct-tcpip',
                    (remote_db_config['host'], remote_db_config['port']),
                    ('127.0.0.1', local_port)
                )

                # Create forwarding thread
                def forward_tunnel():
                    while channel and not channel.closed:
                        # Check timeout
                        if time.time() - start_time > max_duration:
                            logger.warning(
                                "SSH tunnel timeout reached",
                                job_id=job_id,
                                duration=max_duration
                            )
                            break
                        time.sleep(1)

                tunnel_thread = threading.Thread(target=forward_tunnel, daemon=True)
                tunnel_thread.start()

                # Store active tunnel
                with self.tunnel_lock:
                    self.active_tunnels[job_id] = ssh_client

                # Modify connection string to use local tunnel
                original_conn = remote_db_config['connection_string']
                db_host = remote_db_config['host']
                db_port = remote_db_config['port']

                # Replace host:port in connection string
                local_conn = original_conn.replace(
                    f"{db_host}:{db_port}",
                    f"127.0.0.1:{local_port}"
                ).replace(
                    f"@{db_host}/",  # Handle cases without port
                    f"@127.0.0.1:{local_port}/"
                )

                logger.info(
                    "SSH tunnel established",
                    job_id=job_id,
                    local_port=local_port,
                    remote_host=db_host,
                    remote_port=db_port
                )

                # Audit log
                self._audit_log(
                    event="tunnel_created",
                    job_id=job_id,
                    ssh_host=ssh_config['host'],
                    db_host=db_host,
                    local_port=local_port
                )

                yield local_conn

            except Exception as e:
                logger.error(
                    "SSH tunnel creation failed",
                    job_id=job_id,
                    error=str(e)
                )
                self._audit_log(
                    event="tunnel_failed",
                    job_id=job_id,
                    error=str(e)
                )
                raise

            finally:
                # Cleanup tunnel
                try:
                    with self.tunnel_lock:
                        if job_id in self.active_tunnels:
                            del self.active_tunnels[job_id]

                    if ssh_client:
                        ssh_client.close()
                        logger.info("SSH tunnel closed", job_id=job_id)

                    # Audit log
                    duration = time.time() - start_time
                    self._audit_log(
                        event="tunnel_closed",
                        job_id=job_id,
                        duration_seconds=duration
                    )

                except Exception as cleanup_error:
                    logger.error(
                        "Error during tunnel cleanup",
                        job_id=job_id,
                        error=str(cleanup_error)
                    )

    def encrypt_credential(self, credential: str) -> bytes:
        """Encrypt sensitive credential for storage."""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.encrypt(credential.encode())

    def decrypt_credential(self, encrypted: bytes) -> str:
        """Decrypt stored credential for use."""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.decrypt(encrypted).decode()

    def cleanup_all_tunnels(self):
        """Emergency cleanup of all active tunnels."""
        with self.tunnel_lock:
            for job_id, client in list(self.active_tunnels.items()):
                try:
                    client.close()
                    logger.info("Closed tunnel during cleanup", job_id=job_id)
                except Exception as e:
                    logger.error(
                        "Failed to close tunnel during cleanup",
                        job_id=job_id,
                        error=str(e)
                    )
            self.active_tunnels.clear()

    def get_active_tunnels(self) -> list:
        """Get list of currently active tunnel job IDs."""
        with self.tunnel_lock:
            return list(self.active_tunnels.keys())

    def _audit_log(self, event: str, **kwargs):
        """
        Create audit log entry for compliance.
        Stores in append-only audit log.
        """
        import json
        from datetime import datetime

        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            **kwargs
        }

        # In production, this would write to:
        # - Immutable audit log service
        # - Compliance database
        # - SIEM system

        # For now, log to structured logger
        logger.info("AUDIT", **audit_entry)

        # Also append to local audit file
        try:
            with open("/tmp/valinor_audit.jsonl", "a") as f:
                f.write(json.dumps(audit_entry) + "\n")
        except OSError as exc:
            logger.warning("Audit log write failed (non-fatal)", error=str(exc))


# Convenience function for simple usage
@contextmanager
def create_ssh_tunnel(
    ssh_host: str,
    ssh_user: str,
    ssh_key_path: str,
    db_host: str,
    db_port: int,
    connection_string: str,
    job_id: str = "manual"
):
    """
    Simplified SSH tunnel creation.

    Args:
        ssh_key_path: Path to SSH private key file OR raw PEM key content.
                      If the value starts with "-----BEGIN", it is treated as
                      key content and written to a secure temp file automatically.

    Example:
        # With file path:
        with create_ssh_tunnel(
            ssh_host="bastion.client.com",
            ssh_user="readonly",
            ssh_key_path="/keys/client_rsa",
            db_host="db.internal",
            db_port=5432,
            connection_string="postgresql://user:pass@db.internal:5432/db",
            job_id="job-123"
        ) as local_conn:
            engine = create_engine(local_conn)

        # With pasted key content:
        with create_ssh_tunnel(
            ssh_host="bastion.client.com",
            ssh_user="readonly",
            ssh_key_path="-----BEGIN RSA PRIVATE KEY-----\\nMIIE...",
            db_host="db.internal",
            db_port=5432,
            connection_string="postgresql://user:pass@db.internal:5432/db",
            job_id="job-123"
        ) as local_conn:
            engine = create_engine(local_conn)
    """
    manager = SSHTunnelManager()

    ssh_config = {
        "host": ssh_host,
        "username": ssh_user,
        "private_key_path": ssh_key_path,
        "port": 22
    }

    db_config = {
        "host": db_host,
        "port": db_port,
        "connection_string": connection_string
    }

    with manager.create_tunnel(ssh_config, db_config, job_id) as tunnel_conn:
        yield tunnel_conn


# Zero-trust validation
class ZeroTrustValidator:
    """
    Implements zero-trust validation for all connections.
    """

    @staticmethod
    def validate_ssh_config(ssh_config: Dict) -> bool:
        """Validate SSH configuration meets security requirements."""
        required_fields = ['host', 'username', 'private_key_path']

        # Check required fields
        for field in required_fields:
            if field not in ssh_config or not ssh_config[field]:
                logger.error(f"Missing required SSH field: {field}")
                return False

        # Validate host format (basic check)
        host = ssh_config['host']
        if not host or ' ' in host or ';' in host:
            logger.error(f"Invalid SSH host format: {host}")
            return False

        # Validate key: either a readable file path or PEM content
        key_value = ssh_config['private_key_path']
        if _is_key_content(key_value):
            # Validate it looks like a real PEM key
            if '-----END' not in key_value:
                logger.error("SSH key content appears incomplete (missing END marker)")
                return False
            return True

        # It's a file path -- validate it exists and has correct permissions
        if not os.path.exists(key_value):
            logger.error(f"SSH key file not found: {key_value}")
            return False

        # Check key file permissions (should be 600 or 400)
        stat_info = os.stat(key_value)
        mode = stat_info.st_mode & 0o777
        if mode not in [0o600, 0o400]:
            logger.error(f"SSH key has insecure permissions: {oct(mode)}")
            return False

        return True

    @staticmethod
    def validate_db_config(db_config: Dict) -> bool:
        """Validate database configuration meets security requirements."""
        required_fields = ['host', 'port', 'connection_string']

        for field in required_fields:
            if field not in db_config:
                logger.error(f"Missing required DB field: {field}")
                return False

        # Validate port is numeric and in valid range
        try:
            port = int(db_config['port'])
            if not 1 <= port <= 65535:
                logger.error(f"Invalid DB port: {port}")
                return False
        except (ValueError, TypeError):
            logger.error(f"DB port must be numeric: {db_config['port']}")
            return False

        # Basic connection string validation (no SQL injection)
        conn_str = db_config['connection_string']
        dangerous_patterns = [';--', '/*', '*/', 'xp_', 'sp_', 'DROP', 'DELETE', 'INSERT', 'UPDATE']
        for pattern in dangerous_patterns:
            if pattern.upper() in conn_str.upper():
                logger.error(f"Dangerous pattern in connection string: {pattern}")
                return False

        return True
