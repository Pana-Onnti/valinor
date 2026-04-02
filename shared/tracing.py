"""
Lightweight pipeline tracing — VAL-75.

Emits structured log entries that look like OTel spans (stage start/end
with duration, status, and trace context) using structlog.  This gives
80% of OpenTelemetry's value without adding any new dependencies.

The resulting log lines are parseable from Loki/Grafana with LogQL:

    {app="valinor"} |= "pipeline.stage" | json | stage_name = "cartographer"

Usage:

    from shared.tracing import PipelineTracer

    tracer = PipelineTracer(job_id="abc-123", client_name="acme")
    with tracer.stage("cartographer"):
        entity_map = await run_cartographer(...)

    # Or manual start/end:
    span = tracer.start("narrators")
    try:
        ...
        span.finish()
    except Exception as exc:
        span.finish(error=exc)

    # At pipeline end:
    tracer.finish()  # logs full pipeline summary
"""

import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


class StageSpan:
    """Represents a single pipeline stage execution."""

    def __init__(
        self,
        stage_name: str,
        trace_id: str,
        job_id: str,
        client_name: str,
    ):
        self.stage_name = stage_name
        self.trace_id = trace_id
        self.job_id = job_id
        self.client_name = client_name
        self.span_id = uuid.uuid4().hex[:16]
        self._start_time = time.perf_counter()
        self._start_wall = time.time()
        self.status: str = "in_progress"
        self.duration_ms: Optional[float] = None
        self.error_message: Optional[str] = None
        self.attributes: Dict[str, Any] = {}

        logger.info(
            "pipeline.stage.start",
            trace_id=self.trace_id,
            span_id=self.span_id,
            job_id=self.job_id,
            client=self.client_name,
            stage_name=self.stage_name,
        )

    def set_attribute(self, key: str, value: Any) -> None:
        """Attach an arbitrary key-value attribute to this span."""
        self.attributes[key] = value

    def finish(self, error: Optional[Exception] = None) -> None:
        """Mark the span as finished, logging duration and status."""
        if self.status != "in_progress":
            return  # already finished

        elapsed = time.perf_counter() - self._start_time
        self.duration_ms = round(elapsed * 1000, 1)

        if error is not None:
            self.status = "error"
            self.error_message = str(error)
            logger.error(
                "pipeline.stage.end",
                trace_id=self.trace_id,
                span_id=self.span_id,
                job_id=self.job_id,
                client=self.client_name,
                stage_name=self.stage_name,
                status=self.status,
                duration_ms=self.duration_ms,
                error=self.error_message,
                **self.attributes,
            )
        else:
            self.status = "success"
            logger.info(
                "pipeline.stage.end",
                trace_id=self.trace_id,
                span_id=self.span_id,
                job_id=self.job_id,
                client=self.client_name,
                stage_name=self.stage_name,
                status=self.status,
                duration_ms=self.duration_ms,
                **self.attributes,
            )

    def as_dict(self) -> Dict[str, Any]:
        """Return a summary dict for the pipeline-level trace."""
        return {
            "stage": self.stage_name,
            "span_id": self.span_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            **({"error": self.error_message} if self.error_message else {}),
            **self.attributes,
        }


class PipelineTracer:
    """
    Traces a full pipeline execution as a series of stage spans.

    Creates a unique trace_id per pipeline run and correlates all
    stage spans under it.
    """

    def __init__(self, job_id: str, client_name: str):
        self.trace_id = uuid.uuid4().hex
        self.job_id = job_id
        self.client_name = client_name
        self._pipeline_start = time.perf_counter()
        self._spans: List[StageSpan] = []

        logger.info(
            "pipeline.trace.start",
            trace_id=self.trace_id,
            job_id=self.job_id,
            client=self.client_name,
        )

    def start(self, stage_name: str) -> StageSpan:
        """Start a new stage span and return it for manual finish."""
        span = StageSpan(
            stage_name=stage_name,
            trace_id=self.trace_id,
            job_id=self.job_id,
            client_name=self.client_name,
        )
        self._spans.append(span)
        return span

    @contextmanager
    def stage(self, stage_name: str):
        """Context manager that auto-finishes the span on exit."""
        span = self.start(stage_name)
        try:
            yield span
            span.finish()
        except Exception as exc:
            span.finish(error=exc)
            raise

    def finish(self) -> Dict[str, Any]:
        """
        Finalize the pipeline trace and log a summary.

        Returns a dict with total duration and per-stage breakdown
        suitable for inclusion in the job results.
        """
        total_ms = round((time.perf_counter() - self._pipeline_start) * 1000, 1)
        stages_summary = [s.as_dict() for s in self._spans]
        failed = [s.stage_name for s in self._spans if s.status == "error"]
        overall_status = "error" if failed else "success"

        logger.info(
            "pipeline.trace.end",
            trace_id=self.trace_id,
            job_id=self.job_id,
            client=self.client_name,
            status=overall_status,
            total_duration_ms=total_ms,
            stages_count=len(self._spans),
            failed_stages=failed or None,
        )

        return {
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "status": overall_status,
            "total_duration_ms": total_ms,
            "stages": stages_summary,
        }
