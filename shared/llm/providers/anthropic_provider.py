"""
Anthropic API provider implementation.
Wraps the official Anthropic SDK with our unified interface.

VAL-31: Added KV-cache support via cache_control blocks in system prompts,
and token tracking via TokenTracker.
"""

import asyncio
import logging
import os
from typing import AsyncIterator, Dict, Any, Optional, List, Union
import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message

from ..base import LLMProvider, LLMResponse, LLMOptions, ModelType

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """
    Official Anthropic API provider using the SDK.
    Production-ready with retry logic, streaming, and error handling.

    VAL-31 additions:
    - KV-cache: when use_kv_cache=True (default when ENABLE_TOKEN_TRACKING env var is set),
      static system prompts are wrapped with cache_control={"type": "ephemeral"} blocks,
      enabling Anthropic's prompt caching (~90% cost reduction on repeated prompts).
    - Token tracking: usage including cache_read_input_tokens and
      cache_creation_input_tokens is captured and forwarded to TokenTracker.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client: Optional[AsyncAnthropic] = None
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.timeout = config.get("timeout", 300)
        self.max_retries = config.get("max_retries", 3)
        # KV-cache enabled by default when token tracking is on
        self.use_kv_cache: bool = config.get(
            "use_kv_cache",
            os.getenv("ENABLE_TOKEN_TRACKING", "true").lower() in ("true", "1", "yes"),
        )
        self.agent_name: str = config.get("agent_name", "unknown")

    async def initialize(self) -> None:
        """Initialize Anthropic client with config"""
        if self._initialized:
            return

        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self.client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries
        )

        # Verify connection with a minimal request
        await self.health_check()
        self._initialized = True

    async def query(
        self,
        prompt: str,
        options: Optional[LLMOptions] = None
    ) -> Union[LLMResponse, AsyncIterator[str]]:
        """Execute query using Anthropic API"""
        if not self._initialized:
            await self.initialize()

        options = options or LLMOptions()
        self.validate_options(options)

        # Build message format for Anthropic
        messages = [{"role": "user", "content": prompt}]

        # Prepare API parameters
        params = {
            "model": options._map_model_to_anthropic(),
            "messages": messages,
            "max_tokens": options.max_tokens or 4096,
            "temperature": options.temperature,
            "stream": options.stream
        }

        if options.system_prompt:
            if self.use_kv_cache:
                # Wrap static system prompt with cache_control for KV-cache
                params["system"] = [
                    {
                        "type": "text",
                        "text": options.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                params["system"] = options.system_prompt

        if options.stop_sequences:
            params["stop_sequences"] = options.stop_sequences

        if options.tools:
            params["tools"] = self._convert_tools(options.tools)

        # Enable prompt caching beta header when KV-cache is on
        if self.use_kv_cache:
            params.setdefault("extra_headers", {})
            params["extra_headers"]["anthropic-beta"] = "prompt-caching-2024-07-31"

        try:
            if options.stream:
                return self._stream_response(params)
            else:
                response = await self.client.messages.create(**params)
                self._track_tokens(response)
                return self._format_response(response)

        except anthropic.RateLimitError as e:
            # Handle rate limiting with exponential backoff
            retry_after = int(e.response.headers.get("retry-after", 60))
            await asyncio.sleep(retry_after)
            return await self.query(prompt, options)  # Retry

        except anthropic.APIError as e:
            # Log and potentially fallback
            raise Exception(f"Anthropic API error: {str(e)}")

    async def _stream_response(self, params: Dict[str, Any]) -> AsyncIterator[str]:
        """Handle streaming responses"""
        async with self.client.messages.stream(**params) as stream:
            async for chunk in stream:
                if chunk.type == "content_block_delta":
                    yield chunk.delta.text

    def _track_tokens(self, response: Message) -> None:
        """
        Capture token usage (including cache metrics) and forward to TokenTracker.
        Safe to call: silently no-ops if tracker unavailable.
        """
        try:
            from shared.llm.token_tracker import TokenTracker

            usage = response.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

            TokenTracker.get_instance().record(
                agent=self.agent_name,
                model=response.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
            )
        except (ImportError, AttributeError, TypeError) as exc:
            logger.warning("Token tracking failed (non-fatal): %s", exc)

    def _format_response(self, response: Message) -> LLMResponse:
        """Convert Anthropic response to unified format"""
        content = response.content[0].text if response.content else ""

        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
            finish_reason=response.stop_reason,
            metadata={
                "id": response.id,
                "role": response.role,
            },
            raw_response=response,
        )

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert generic tool format to Anthropic format"""
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool.get("name"),
                "description": tool.get("description"),
                "input_schema": tool.get("parameters", {})
            })
        return anthropic_tools

    async def health_check(self) -> bool:
        """Verify API connectivity"""
        try:
            # Use a minimal request to check connectivity
            await self.client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Clean up client resources"""
        if self.client:
            await self.client.close()
        self._initialized = False

    def supported_models(self) -> List[ModelType]:
        """Return Anthropic-supported models"""
        return [ModelType.OPUS, ModelType.SONNET, ModelType.HAIKU]

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: ModelType) -> float:
        """Estimate cost based on Anthropic pricing"""
        # Pricing as of 2025 (per 1M tokens)
        pricing = {
            ModelType.OPUS: {"input": 15.00, "output": 75.00},
            ModelType.SONNET: {"input": 3.00, "output": 15.00},
            ModelType.HAIKU: {"input": 0.25, "output": 1.25}
        }

        model_pricing = pricing.get(model, pricing[ModelType.SONNET])
        input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]

        return input_cost + output_cost
