"""
Anthropic Batch API provider — VAL-25.

Wraps AnthropicProvider to support the Message Batches API for
non-interactive workloads, achieving 50 % cost reduction on input tokens.

Batch requests are submitted, polled with exponential backoff, and results
collected.  On any batch-level failure the provider falls back to the
standard interactive API transparently.

Usage:
    from shared.llm.providers.batch_provider import BatchAnthropicProvider

    provider = BatchAnthropicProvider(config={...})
    await provider.initialize()

    results = await provider.query_batch(requests=[
        {"custom_id": "req-1", "prompt": "...", "options": LLMOptions(...)},
        {"custom_id": "req-2", "prompt": "...", "options": LLMOptions(...)},
    ])
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ..base import LLMOptions, LLMResponse
from .anthropic_provider import AnthropicProvider

logger = structlog.get_logger()

# ── Polling constants ────────────────────────────────────────────────────────

_INITIAL_POLL_INTERVAL_S = 10
_MAX_POLL_INTERVAL_S = 300  # 5 min
_POLL_BACKOFF_FACTOR = 2


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class BatchRequest:
    """A single request within a batch."""
    custom_id: str
    prompt: str
    options: Optional[LLMOptions] = None


@dataclass
class BatchResult:
    """Result for a single request within a batch."""
    custom_id: str
    response: Optional[LLMResponse] = None
    error: Optional[str] = None
    succeeded: bool = False


@dataclass
class BatchJob:
    """Metadata for a submitted batch job."""
    batch_id: str
    status: str = "in_progress"
    total_requests: int = 0
    results: List[BatchResult] = field(default_factory=list)


# ── Provider ─────────────────────────────────────────────────────────────────

class BatchAnthropicProvider:
    """
    Wraps :class:`AnthropicProvider` to add Anthropic Message Batches API
    support.  The interactive ``query()`` method is delegated unchanged;
    batch-specific methods are layered on top.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self._provider = AnthropicProvider(config)

    # ── Lifecycle delegates ──────────────────────────────────────────────

    async def initialize(self) -> None:
        await self._provider.initialize()

    async def close(self) -> None:
        await self._provider.close()

    async def health_check(self) -> bool:
        return await self._provider.health_check()

    # ── Interactive passthrough ──────────────────────────────────────────

    async def query(self, prompt: str, options: Optional[LLMOptions] = None) -> LLMResponse:
        """Delegate to the standard interactive API."""
        return await self._provider.query(prompt, options)

    # ── Batch API ────────────────────────────────────────────────────────

    async def submit_batch(self, requests: List[BatchRequest]) -> BatchJob:
        """
        Submit a list of requests as a single Message Batch.

        Returns a :class:`BatchJob` with the server-assigned ``batch_id``.
        """
        if not self._provider._initialized:
            await self.initialize()

        api_requests = []
        for req in requests:
            opts = req.options or LLMOptions(stream=False)
            params: Dict[str, Any] = {
                "model": opts._map_model_to_anthropic(),
                "max_tokens": opts.max_tokens or 4096,
                "messages": [{"role": "user", "content": req.prompt}],
            }
            if opts.system_prompt:
                params["system"] = opts.system_prompt
            if opts.temperature is not None:
                params["temperature"] = opts.temperature

            api_requests.append({
                "custom_id": req.custom_id,
                "params": params,
            })

        logger.info(
            "batch.submit",
            request_count=len(api_requests),
        )

        batch = await self._provider.client.messages.batches.create(
            requests=api_requests,
        )

        return BatchJob(
            batch_id=batch.id,
            status=batch.processing_status,
            total_requests=len(api_requests),
        )

    async def poll_batch(self, batch_job: BatchJob) -> BatchJob:
        """
        Poll a previously submitted batch until ``processing_status == "ended"``.

        Uses exponential back-off: 10 s → 20 s → 40 s … capped at 5 min.
        """
        if not self._provider._initialized:
            await self.initialize()

        interval = _INITIAL_POLL_INTERVAL_S

        while True:
            batch = await self._provider.client.messages.batches.retrieve(
                batch_job.batch_id,
            )
            batch_job.status = batch.processing_status
            logger.debug(
                "batch.poll",
                batch_id=batch_job.batch_id,
                status=batch_job.status,
                poll_interval_s=interval,
            )

            if batch.processing_status == "ended":
                break

            await asyncio.sleep(interval)
            interval = min(interval * _POLL_BACKOFF_FACTOR, _MAX_POLL_INTERVAL_S)

        # Collect results
        batch_job.results = await self._collect_results(batch_job)
        return batch_job

    async def query_batch(
        self,
        requests: List[BatchRequest],
        *,
        fallback_on_error: bool = True,
    ) -> List[BatchResult]:
        """
        High-level helper: submit → poll → return results.

        If the batch submission or polling fails and *fallback_on_error* is
        ``True``, each request is executed via the standard interactive API.
        """
        try:
            job = await self.submit_batch(requests)
            job = await self.poll_batch(job)
            return job.results

        except Exception as exc:
            logger.warning(
                "batch.failed_falling_back",
                error=str(exc),
                fallback=fallback_on_error,
            )
            if not fallback_on_error:
                raise

            return await self._fallback_interactive(requests)

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _collect_results(self, batch_job: BatchJob) -> List[BatchResult]:
        """Iterate over batch results and convert to :class:`BatchResult`."""
        results: List[BatchResult] = []

        async for entry in self._provider.client.messages.batches.results(
            batch_job.batch_id,
        ):
            if entry.result.type == "succeeded":
                message = entry.result.message
                self._track_batch_tokens(message)
                llm_resp = self._provider._format_response(message)
                results.append(BatchResult(
                    custom_id=entry.custom_id,
                    response=llm_resp,
                    succeeded=True,
                ))
            else:
                error_msg = getattr(entry.result, "error", None)
                error_str = str(error_msg) if error_msg else "unknown batch error"
                results.append(BatchResult(
                    custom_id=entry.custom_id,
                    error=error_str,
                    succeeded=False,
                ))

        return results

    def _track_batch_tokens(self, message: Any) -> None:
        """
        Record token usage for a batch result with the 50 % batch discount.

        The Batch API charges 50 % of standard input-token pricing.  We
        record this via :meth:`TokenTracker.record` using the special
        ``is_batch=True`` flag so the tracker can apply the discount.
        """
        try:
            from shared.llm.token_tracker import TokenTracker

            usage = message.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

            TokenTracker.get_instance().record(
                agent=self._provider.agent_name,
                model=message.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
                is_batch=True,
            )
        except (ImportError, AttributeError, TypeError) as exc:
            logger.warning("batch.token_tracking_failed", error=str(exc))

    async def _fallback_interactive(
        self, requests: List[BatchRequest],
    ) -> List[BatchResult]:
        """Execute every request through the interactive API as fallback."""
        logger.info("batch.fallback_interactive", count=len(requests))
        results: List[BatchResult] = []

        for req in requests:
            try:
                opts = req.options or LLMOptions(stream=False)
                # Force non-streaming for fallback
                opts.stream = False
                resp = await self._provider.query(req.prompt, opts)
                results.append(BatchResult(
                    custom_id=req.custom_id,
                    response=resp,
                    succeeded=True,
                ))
            except Exception as exc:
                results.append(BatchResult(
                    custom_id=req.custom_id,
                    error=str(exc),
                    succeeded=False,
                ))

        return results
