"""
Anthropic API provider implementation.
Wraps the official Anthropic SDK with our unified interface.
"""

import asyncio
from typing import AsyncIterator, Dict, Any, Optional, List, Union
import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message

from ..base import LLMProvider, LLMResponse, LLMOptions, ModelType


class AnthropicProvider(LLMProvider):
    """
    Official Anthropic API provider using the SDK.
    Production-ready with retry logic, streaming, and error handling.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client: Optional[AsyncAnthropic] = None
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.timeout = config.get("timeout", 300)
        self.max_retries = config.get("max_retries", 3)
    
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
            params["system"] = options.system_prompt
        
        if options.stop_sequences:
            params["stop_sequences"] = options.stop_sequences
        
        if options.tools:
            params["tools"] = self._convert_tools(options.tools)
        
        try:
            if options.stream:
                return self._stream_response(params)
            else:
                response = await self.client.messages.create(**params)
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
    
    def _format_response(self, response: Message) -> LLMResponse:
        """Convert Anthropic response to unified format"""
        content = response.content[0].text if response.content else ""
        
        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens
            },
            finish_reason=response.stop_reason,
            metadata={
                "id": response.id,
                "role": response.role
            },
            raw_response=response
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
            response = await self.client.messages.create(
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