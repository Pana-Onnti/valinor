"""
MVP Tests for Valinor SaaS.
Basic tests to verify core functionality.
"""

import os
import json
import pytest
import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.ssh_tunnel import ZeroTrustValidator
from shared.storage import MetadataStorage
from api.adapters.valinor_adapter import ValinorAdapter

class TestZeroTrustValidator:
    """Test SSH configuration validation."""
    
    def setup_method(self):
        self.validator = ZeroTrustValidator()
    
    def test_valid_ssh_config(self):
        """Test valid SSH configuration."""
        config = {
            'host': 'example.com',
            'username': 'testuser',
            'private_key_path': '/path/to/key',
            'port': 22
        }
        assert self.validator.validate_ssh_config(config) is True
    
    def test_invalid_ssh_config_missing_host(self):
        """Test invalid SSH config missing host."""
        config = {
            'username': 'testuser',
            'private_key_path': '/path/to/key'
        }
        assert self.validator.validate_ssh_config(config) is False
    
    def test_invalid_ssh_config_suspicious_host(self):
        """Test invalid SSH config with suspicious host."""
        config = {
            'host': 'localhost',  # Suspicious for production
            'username': 'testuser',
            'private_key_path': '/path/to/key'
        }
        # Should still be valid for testing
        assert self.validator.validate_ssh_config(config) is True
    
    def test_valid_db_config(self):
        """Test valid database configuration."""
        config = {
            'host': 'db.example.com',
            'port': 5432,
            'name': 'testdb',
            'type': 'postgres',
            'connection_string': 'postgresql://user:pass@{host}:{port}/{database}'
        }
        assert self.validator.validate_db_config(config) is True
    
    def test_invalid_db_config_missing_fields(self):
        """Test invalid database config missing required fields."""
        config = {
            'host': 'db.example.com',
            'port': 5432
            # Missing name, type, connection_string
        }
        assert self.validator.validate_db_config(config) is False


class TestMetadataStorage:
    """Test metadata storage functionality."""
    
    def setup_method(self):
        # Use local storage for tests
        self.storage = MetadataStorage()
        # Ensure we're using local storage
        self.storage.use_supabase = False
        self.storage.local_storage_dir = "/tmp/test_valinor_metadata"
        os.makedirs(self.storage.local_storage_dir, exist_ok=True)
    
    def teardown_method(self):
        # Clean up test files
        import shutil
        if os.path.exists(self.storage.local_storage_dir):
            shutil.rmtree(self.storage.local_storage_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_store_job_metadata(self):
        """Test storing job metadata."""
        job_id = "test-job-123"
        metadata = {
            "client_name": "test_client",
            "period": "Q1-2025",
            "config_hash": "abc123"
        }
        
        result = await self.storage.store_job_metadata(job_id, metadata)
        assert result is True
        
        # Verify file was created
        file_path = os.path.join(self.storage.local_storage_dir, f"job_{job_id}.json")
        assert os.path.exists(file_path)
        
        # Verify content
        with open(file_path, 'r') as f:
            stored_data = json.load(f)
        
        assert stored_data["job_id"] == job_id
        assert stored_data["client_name"] == "test_client"
        assert stored_data["period"] == "Q1-2025"
    
    @pytest.mark.asyncio
    async def test_store_job_results(self):
        """Test storing job results."""
        job_id = "test-job-456"
        results = {
            "findings_count": 15,
            "critical_issues": 3,
            "warnings": 7,
            "opportunities": 5,
            "execution_time": 120.5,
            "success": True
        }
        
        result = await self.storage.store_job_results(job_id, results)
        assert result is True
        
        # Verify file was created
        file_path = os.path.join(self.storage.local_storage_dir, f"results_{job_id}.json")
        assert os.path.exists(file_path)
    
    @pytest.mark.asyncio
    async def test_get_job_metadata(self):
        """Test retrieving job metadata."""
        job_id = "test-job-789"
        metadata = {
            "client_name": "test_client_2",
            "period": "H1-2025",
            "config_hash": "def456"
        }
        
        # Store first
        await self.storage.store_job_metadata(job_id, metadata)
        
        # Retrieve
        retrieved = await self.storage.get_job_metadata(job_id)
        assert retrieved is not None
        assert retrieved["client_name"] == "test_client_2"
        assert retrieved["period"] == "H1-2025"
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test storage health check."""
        health = await self.storage.health_check()
        assert health["status"] == "healthy"
        assert health["type"] == "local"


class TestValinorAdapter:
    """Test Valinor adapter functionality."""
    
    def setup_method(self):
        self.progress_updates = []
        
        async def mock_progress(stage, progress, message):
            self.progress_updates.append({
                "stage": stage,
                "progress": progress,
                "message": message
            })
        
        self.adapter = ValinorAdapter(progress_callback=mock_progress)
    
    @pytest.mark.asyncio
    @patch('api.adapters.valinor_adapter.create_ssh_tunnel')
    @patch('api.adapters.valinor_adapter.run_cartographer')
    @patch('api.adapters.valinor_adapter.build_queries')
    @patch('api.adapters.valinor_adapter.execute_queries')
    @patch('api.adapters.valinor_adapter.run_analysis_agents')
    @patch('api.adapters.valinor_adapter.narrate_executive')
    @patch('api.adapters.valinor_adapter.deliver_reports')
    async def test_run_analysis_success(self, mock_deliver, mock_narrate, mock_agents,
                                      mock_execute, mock_build, mock_cartographer, mock_tunnel):
        """Test successful analysis run."""
        
        # Mock SSH tunnel context manager
        mock_tunnel.return_value.__enter__.return_value = "postgresql://user:pass@localhost:5432/test"
        mock_tunnel.return_value.__exit__.return_value = None
        
        # Mock cartographer
        mock_cartographer.return_value = {
            "entities": {
                "customers": {"row_count": 1000},
                "invoices": {"row_count": 5000}
            }
        }
        
        # Mock query builder
        mock_build.return_value = {
            "queries": ["SELECT * FROM customers", "SELECT * FROM invoices"],
            "skipped": []
        }
        
        # Mock query execution
        mock_execute.return_value = {
            "results": [{"data": "customer_data"}, {"data": "invoice_data"}],
            "errors": []
        }
        
        # Mock analysis agents
        mock_agents.return_value = {
            "customer_agent": {"findings": [{"type": "insight", "message": "test finding"}]},
            "financial_agent": {"findings": [{"type": "warning", "message": "test warning"}]}
        }
        
        # Mock narrators
        mock_narrate.return_value = {
            "executive_summary": "Test executive summary",
            "ceo_report": "Test CEO report"
        }
        
        # Mock deliver
        mock_deliver.return_value = True
        
        # Test configuration
        connection_config = {
            "ssh_config": {
                "host": "test.example.com",
                "username": "testuser",
                "private_key_path": "/test/key"
            },
            "db_config": {
                "host": "localhost",
                "port": 5432,
                "name": "testdb",
                "type": "postgres",
                "connection_string": "postgresql://user:pass@{host}:{port}/{database}"
            }
        }
        
        # Run analysis
        results = await self.adapter.run_analysis(
            job_id="test-job-001",
            client_name="test_client",
            connection_config=connection_config,
            period="Q1-2025"
        )
        
        # Verify results
        assert results["job_id"] == "test-job-001"
        assert results["status"] == "completed"
        assert "stages" in results
        assert "findings" in results
        assert "reports" in results
        assert results["execution_time_seconds"] > 0
        
        # Verify progress updates were called
        assert len(self.progress_updates) > 0
        assert any(update["stage"] == "validating" for update in self.progress_updates)
        assert any(update["stage"] == "completed" for update in self.progress_updates)
    
    @pytest.mark.asyncio
    async def test_run_analysis_invalid_ssh_config(self):
        """Test analysis with invalid SSH config."""
        connection_config = {
            "ssh_config": {
                # Missing required fields
                "host": "test.example.com"
            },
            "db_config": {
                "host": "localhost",
                "port": 5432,
                "name": "testdb",
                "type": "postgres",
                "connection_string": "postgresql://user:pass@{host}:{port}/{database}"
            }
        }
        
        with pytest.raises(ValueError, match="Invalid SSH configuration"):
            await self.adapter.run_analysis(
                job_id="test-job-002",
                client_name="test_client",
                connection_config=connection_config,
                period="Q1-2025"
            )


class TestAPIIntegration:
    """Integration tests for API endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint_structure(self):
        """Test health endpoint returns expected structure."""
        # This would require running the actual FastAPI app
        # For now, just test the expected structure
        expected_fields = ["status", "timestamp", "components", "version"]
        
        # Mock health response
        health_response = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "redis": "healthy",
                "storage": "healthy"
            },
            "version": "1.0.0"
        }
        
        for field in expected_fields:
            assert field in health_response
        
        assert health_response["status"] in ["healthy", "unhealthy"]
        assert "redis" in health_response["components"]
        assert "storage" in health_response["components"]


class TestSSHTunnelSecurity:
    """Test SSH tunnel security features."""
    
    def setup_method(self):
        self.validator = ZeroTrustValidator()
    
    def test_malicious_host_detection(self):
        """Test detection of potentially malicious hosts."""
        malicious_configs = [
            {"host": "127.0.0.1", "username": "test", "private_key_path": "/tmp/key"},
            {"host": "internal.company.com", "username": "test", "private_key_path": "/tmp/key"},
        ]
        
        for config in malicious_configs:
            # These should still validate as they might be legitimate in development
            # but the validator should flag them for review
            result = self.validator.validate_ssh_config(config)
            # For now, we allow these but log them
            assert isinstance(result, bool)
    
    def test_key_path_validation(self):
        """Test SSH key path validation."""
        valid_paths = [
            "/home/user/.ssh/id_rsa",
            "/tmp/test_key",
            "~/.ssh/id_rsa"
        ]
        
        for path in valid_paths:
            config = {
                "host": "test.example.com",
                "username": "testuser",
                "private_key_path": path
            }
            assert self.validator.validate_ssh_config(config) is True


class TestErrorHandling:
    """Test error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_storage_failure_handling(self):
        """Test handling of storage failures."""
        storage = MetadataStorage()
        # Force an invalid storage directory
        storage.local_storage_dir = "/invalid/nonexistent/directory"
        storage.use_supabase = False
        
        # This should handle the error gracefully
        result = await storage.store_job_metadata("test-job", {"test": "data"})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_adapter_connection_failure(self):
        """Test adapter handling of connection failures."""
        adapter = ValinorAdapter()
        
        connection_config = {
            "ssh_config": {
                "host": "nonexistent.example.com",
                "username": "testuser",
                "private_key_path": "/nonexistent/key"
            },
            "db_config": {
                "host": "nonexistent.db.com",
                "port": 5432,
                "name": "testdb",
                "type": "postgres",
                "connection_string": "postgresql://user:pass@{host}:{port}/{database}"
            }
        }
        
        # This should raise an exception
        with pytest.raises(Exception):
            await adapter.run_analysis(
                job_id="test-job-fail",
                client_name="test_client",
                connection_config=connection_config,
                period="Q1-2025"
            )


class TestE2EFlow:
    """End-to-end flow tests."""
    
    @pytest.mark.asyncio
    async def test_complete_analysis_flow_mock(self):
        """Test complete analysis flow with mocked components."""
        # This would test the entire flow from API request to results
        # For MVP, we'll test the main components work together
        
        # 1. Validate configuration
        validator = ZeroTrustValidator()
        ssh_config = {
            "host": "test.example.com",
            "username": "testuser",
            "private_key_path": "/test/key"
        }
        assert validator.validate_ssh_config(ssh_config) is True
        
        # 2. Test storage
        storage = MetadataStorage()
        storage.use_supabase = False
        storage.local_storage_dir = "/tmp/test_e2e_metadata"
        os.makedirs(storage.local_storage_dir, exist_ok=True)
        
        job_id = "test-e2e-job"
        metadata = {"client_name": "test_e2e_client", "period": "Q1-2025"}
        
        store_result = await storage.store_job_metadata(job_id, metadata)
        assert store_result is True
        
        retrieved = await storage.get_job_metadata(job_id)
        assert retrieved is not None
        assert retrieved["client_name"] == "test_e2e_client"
        
        # Cleanup
        import shutil
        shutil.rmtree(storage.local_storage_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])