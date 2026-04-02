"""
Celery application factory for Valinor SaaS worker.
Configured entirely from environment variables.
"""

import os
from celery import Celery

# Redis URL — default matches the Docker Compose host port mapping
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

celery_app = Celery(
    "valinor_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["worker.tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reliability
    task_track_started=True,
    task_time_limit=3600,        # 1 hour hard limit
    task_soft_time_limit=3300,   # 55-minute soft limit
    worker_max_tasks_per_child=10,
    worker_prefetch_multiplier=1,
    # Routes — heavy analysis on dedicated queue, lightweight ops on maintenance
    task_routes={
        "worker.tasks.run_analysis_task": {"queue": "analysis"},
        "worker.tasks.cleanup_job": {"queue": "maintenance"},
        "worker.tasks.cleanup_expired_jobs": {"queue": "maintenance"},
        "worker.tasks.health_check": {"queue": "maintenance"},
        "worker.tasks.monitor_jobs": {"queue": "maintenance"},
    },
    # Default queue for any unrouted tasks
    task_default_queue="maintenance",
    # Beat schedule
    beat_schedule={
        "cleanup-expired-jobs": {
            "task": "worker.tasks.cleanup_expired_jobs",
            "schedule": 6 * 3600,  # every 6 hours
        },
    },
)
