"""
Metadata Storage for Valinor SaaS.
Stores only metadata and aggregated results, NO client data.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import structlog

try:
    from supabase import create_client, Client as SupabaseClient
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    SupabaseClient = None  # type: ignore

logger = structlog.get_logger()


class MetadataStorage:
    """
    Stores job metadata and aggregated results.
    NO client data is stored, only metadata for tracking and compliance.
    """

    def __init__(self):
        """Initialize metadata storage with Supabase or fallback to local."""
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')

        if _SUPABASE_AVAILABLE and self.supabase_url and self.supabase_key:
            try:
                self.supabase = create_client(
                    self.supabase_url,
                    self.supabase_key
                )
                self.use_supabase = True
                logger.info("Using Supabase for metadata storage")
            except Exception as e:
                logger.warning(f"Failed to connect to Supabase: {e}")
                self.supabase = None
                self.use_supabase = False
        else:
            logger.info("Using local file storage for metadata")
            self.supabase = None
            self.use_supabase = False

        # Local storage fallback directory
        self.local_storage_dir = "/tmp/valinor_metadata"
        os.makedirs(self.local_storage_dir, exist_ok=True)

    async def store_job_metadata(self, job_id: str, metadata: Dict[str, Any]) -> bool:
        """
        Store job execution metadata.

        Args:
            job_id: Unique job identifier
            metadata: Job metadata (no sensitive data)
                - client_name: Client identifier
                - period: Analysis period
                - config_hash: Hash of configuration
                - started_at: Start timestamp

        Returns:
            Success status
        """
        try:
            # Ensure no sensitive data
            safe_metadata = {
                "job_id": job_id,
                "client_name": metadata.get("client_name", "unknown"),
                "period": metadata.get("period", "unknown"),
                "config_hash": metadata.get("config_hash", ""),
                "started_at": datetime.utcnow().isoformat(),
                "status": "started"
            }

            if self.use_supabase and self.supabase:
                # Store in Supabase
                self.supabase.table('analysis_jobs').insert(safe_metadata).execute()
            else:
                # Store locally
                file_path = os.path.join(self.local_storage_dir, f"job_{job_id}.json")
                with open(file_path, 'w') as f:
                    json.dump(safe_metadata, f, indent=2)

            logger.info(
                "Stored job metadata",
                job_id=job_id,
                client=safe_metadata["client_name"]
            )
            return True

        except Exception as e:
            logger.error(f"Failed to store job metadata: {e}")
            return False

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        additional_data: Optional[Dict] = None
    ) -> bool:
        """
        Update job status and progress.

        Args:
            job_id: Job identifier
            status: New status (processing, completed, failed)
            additional_data: Additional metadata to store

        Returns:
            Success status
        """
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.utcnow().isoformat()
            }

            if additional_data:
                # Filter out sensitive data
                safe_data = {
                    k: v for k, v in additional_data.items()
                    if k not in ["password", "secret", "key", "token"]
                }
                update_data.update(safe_data)

            if self.use_supabase and self.supabase:
                self.supabase.table('analysis_jobs').update(update_data).eq(
                    'job_id', job_id
                ).execute()
            else:
                # Update local file
                file_path = os.path.join(self.local_storage_dir, f"job_{job_id}.json")
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    data.update(update_data)
                    with open(file_path, 'w') as f:
                        json.dump(data, f, indent=2)

            return True

        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
            return False

    async def store_job_results(self, job_id: str, results: Dict[str, Any]) -> bool:
        """
        Store aggregated job results (no client data).

        Args:
            job_id: Job identifier
            results: Aggregated results
                - findings_count: Number of findings
                - critical_issues: Count of critical issues
                - execution_time: Total execution time
                - success: Success status

        Returns:
            Success status
        """
        try:
            # Store only aggregated metrics, no actual data
            safe_results = {
                "job_id": job_id,
                "findings_count": results.get("findings_count", 0),
                "critical_issues": results.get("critical_issues", 0),
                "warnings": results.get("warnings", 0),
                "opportunities": results.get("opportunities", 0),
                "execution_time_seconds": results.get("execution_time", 0),
                "success": results.get("success", False),
                "completed_at": datetime.utcnow().isoformat()
            }

            if results.get("error"):
                safe_results["error_type"] = type(results["error"]).__name__
                # Don't store error message as it might contain sensitive info

            if self.use_supabase and self.supabase:
                self.supabase.table('analysis_results').insert(safe_results).execute()
            else:
                file_path = os.path.join(
                    self.local_storage_dir,
                    f"results_{job_id}.json"
                )
                with open(file_path, 'w') as f:
                    json.dump(safe_results, f, indent=2)

            logger.info(
                "Stored job results",
                job_id=job_id,
                findings=safe_results["findings_count"]
            )
            return True

        except Exception as e:
            logger.error(f"Failed to store job results: {e}")
            return False

    async def get_job_metadata(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve job metadata.

        Args:
            job_id: Job identifier

        Returns:
            Job metadata or None
        """
        try:
            if self.use_supabase and self.supabase:
                response = self.supabase.table('analysis_jobs').select("*").eq(
                    'job_id', job_id
                ).execute()
                if response.data:
                    return response.data[0]
            else:
                file_path = os.path.join(self.local_storage_dir, f"job_{job_id}.json")
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        return json.load(f)

            return None

        except Exception as e:
            logger.error(f"Failed to retrieve job metadata: {e}")
            return None

    async def get_client_memory(
        self,
        client_name: str,
        period: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve client memory from previous analyses.

        Args:
            client_name: Client identifier
            period: Optional period to retrieve specific memory

        Returns:
            Memory dictionary or None
        """
        try:
            if self.use_supabase and self.supabase:
                query = self.supabase.table('client_memory').select("*").eq(
                    'client_name', client_name
                )
                if period:
                    query = query.eq('period', period)

                response = query.order('created_at', desc=True).limit(1).execute()

                if response.data:
                    return json.loads(response.data[0].get('memory', '{}'))
            else:
                # Local storage
                pattern = f"memory_{client_name}_{period}.json" if period else f"memory_{client_name}_*.json"
                import glob
                files = glob.glob(os.path.join(self.local_storage_dir, pattern))
                if files:
                    # Get most recent
                    latest_file = max(files, key=os.path.getctime)
                    with open(latest_file, 'r') as f:
                        return json.load(f)

            return None

        except Exception as e:
            logger.error(f"Failed to retrieve client memory: {e}")
            return None

    async def store_client_memory(
        self,
        client_name: str,
        period: str,
        memory: Dict[str, Any]
    ) -> bool:
        """
        Store client memory for future analyses.

        Args:
            client_name: Client identifier
            period: Analysis period
            memory: Memory data (aggregated, no sensitive info)

        Returns:
            Success status
        """
        try:
            # Ensure no sensitive data in memory
            safe_memory = {
                "previous_run": memory.get("previous_run", {}),
                "entity_map_snapshot": {
                    "tables": memory.get("entity_map_snapshot", {}).get("tables", []),
                    "row_counts": memory.get("entity_map_snapshot", {}).get("row_counts", {})
                },
                "history": memory.get("history", [])[-10:]  # Keep last 10 runs
            }

            if self.use_supabase and self.supabase:
                self.supabase.table('client_memory').insert({
                    "client_name": client_name,
                    "period": period,
                    "memory": json.dumps(safe_memory),
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
            else:
                file_path = os.path.join(
                    self.local_storage_dir,
                    f"memory_{client_name}_{period}.json"
                )
                with open(file_path, 'w') as f:
                    json.dump(safe_memory, f, indent=2)

            logger.info(
                "Stored client memory",
                client=client_name,
                period=period
            )
            return True

        except Exception as e:
            logger.error(f"Failed to store client memory: {e}")
            return False

    async def cleanup_old_metadata(self, days: int = 90) -> int:
        """
        Clean up old metadata older than specified days.

        Args:
            days: Number of days to keep metadata

        Returns:
            Number of records cleaned up
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            cleaned = 0

            if self.use_supabase and self.supabase:
                # Clean old jobs
                response = self.supabase.table('analysis_jobs').delete().lt(
                    'created_at', cutoff_date.isoformat()
                ).execute()
                cleaned += len(response.data) if response.data else 0

                # Clean old results
                response = self.supabase.table('analysis_results').delete().lt(
                    'completed_at', cutoff_date.isoformat()
                ).execute()
                cleaned += len(response.data) if response.data else 0
            else:
                # Clean local files
                import glob
                import time  # noqa: F401

                cutoff_timestamp = cutoff_date.timestamp()

                for pattern in ['job_*.json', 'results_*.json', 'memory_*.json']:
                    files = glob.glob(os.path.join(self.local_storage_dir, pattern))
                    for file_path in files:
                        if os.path.getctime(file_path) < cutoff_timestamp:
                            os.remove(file_path)
                            cleaned += 1

            logger.info(f"Cleaned up {cleaned} old metadata records")
            return cleaned

        except Exception as e:
            logger.error(f"Failed to cleanup old metadata: {e}")
            return 0

    async def get_client_statistics(self, client_name: str) -> Dict[str, Any]:
        """
        Get aggregated statistics for a client.

        Args:
            client_name: Client identifier

        Returns:
            Statistics dictionary
        """
        try:
            stats = {
                "client_name": client_name,
                "total_analyses": 0,
                "successful_analyses": 0,
                "failed_analyses": 0,
                "average_execution_time": 0,
                "total_findings": 0,
                "last_analysis": None
            }

            if self.use_supabase and self.supabase:
                # Get job statistics
                response = self.supabase.table('analysis_jobs').select("*").eq(
                    'client_name', client_name
                ).execute()

                if response.data:
                    jobs = response.data
                    stats["total_analyses"] = len(jobs)
                    stats["successful_analyses"] = sum(
                        1 for j in jobs if j.get("status") == "completed"
                    )
                    stats["failed_analyses"] = sum(
                        1 for j in jobs if j.get("status") == "failed"
                    )

                    # Get results statistics
                    job_ids = [j["job_id"] for j in jobs]
                    results_response = self.supabase.table('analysis_results').select("*").in_(
                        'job_id', job_ids
                    ).execute()

                    if results_response.data:
                        results = results_response.data
                        exec_times = [r["execution_time_seconds"] for r in results if "execution_time_seconds" in r]
                        if exec_times:
                            stats["average_execution_time"] = sum(exec_times) / len(exec_times)

                        stats["total_findings"] = sum(
                            r.get("findings_count", 0) for r in results
                        )

                    # Get last analysis date
                    latest_job = max(jobs, key=lambda j: j.get("started_at", ""))
                    stats["last_analysis"] = latest_job.get("started_at")

            return stats

        except Exception as e:
            logger.error(f"Failed to get client statistics: {e}")
            return stats

    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of storage systems.

        Returns:
            Health status dictionary
        """
        try:
            if self.use_supabase and self.supabase:
                # Test Supabase connection with a simple query
                self.supabase.table('analysis_jobs').select("count").limit(1).execute()
                storage_status = "healthy"
                storage_type = "supabase"
            else:
                # Test local storage
                test_file = os.path.join(self.local_storage_dir, "health_check.txt")
                with open(test_file, 'w') as f:
                    f.write("health_check")
                os.remove(test_file)
                storage_status = "healthy"
                storage_type = "local"

            return {
                "status": storage_status,
                "type": storage_type,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Storage health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# Supabase table schemas (for reference)
SUPABASE_SCHEMAS = """
-- analysis_jobs table
CREATE TABLE analysis_jobs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    client_name TEXT NOT NULL,
    period TEXT NOT NULL,
    config_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    INDEX idx_job_id (job_id),
    INDEX idx_client_name (client_name),
    INDEX idx_status (status)
);

-- analysis_results table
CREATE TABLE analysis_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_id TEXT REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
    findings_count INTEGER DEFAULT 0,
    critical_issues INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    opportunities INTEGER DEFAULT 0,
    execution_time_seconds INTEGER,
    success BOOLEAN DEFAULT false,
    error_type TEXT,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    INDEX idx_job_id (job_id)
);

-- client_memory table
CREATE TABLE client_memory (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_name TEXT NOT NULL,
    period TEXT NOT NULL,
    memory JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    INDEX idx_client_period (client_name, period)
);

-- audit_log table (append-only)
CREATE TABLE audit_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    event TEXT NOT NULL,
    job_id TEXT,
    client_name TEXT,
    user_id TEXT,
    metadata JSONB,

    INDEX idx_timestamp (timestamp),
    INDEX idx_event (event),
    INDEX idx_job_id (job_id)
);
"""
