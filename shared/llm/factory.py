"""
Factory pattern for creating LLM providers with automatic fallback and monitoring.
Central point for provider instantiation and management.
"""

import asyncio
import os
from typing import Optional, Dict, Any, Type
from contextlib import asynccontextmanager
import logging
from datetime import datetime

from .base import LLMProvider, LLMResponse, LLMOptions
from .config import LLMConfig, ProviderType
from .providers.anthropic_provider import AnthropicProvider
from .providers.cli_provider import ClaudeCliProvider
from .monitoring import MetricsCollector, CostTracker


logger = logging.getLogger(__name__)


class MockProvider(LLMProvider):
    """Mock provider for testing"""
    
    async def initialize(self) -> None:
        self._initialized = True
    
    async def query(self, prompt: str, options: Optional[LLMOptions] = None):
        if options and options.stream:
            async def mock_stream():
                for word in "This is a mock response".split():
                    yield word + " "
            return mock_stream()
        
        return LLMResponse(
            content="This is a mock response",
            model="mock-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    
    async def health_check(self) -> bool:
        return True
    
    async def close(self) -> None:
        self._initialized = False
    
    def supported_models(self):
        from .base import ModelType
        return [ModelType.SONNET]
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model):
        return 0.0


class LLMProviderFactory:
    """
    Factory for creating and managing LLM providers.
    Handles fallback logic, monitoring, and caching.
    """
    
    _providers: Dict[ProviderType, Type[LLMProvider]] = {
        ProviderType.ANTHROPIC_API: AnthropicProvider,
        ProviderType.CONSOLE_CLI: ClaudeCliProvider,
        ProviderType.MOCK: MockProvider,
    }
    
    _instances: Dict[ProviderType, LLMProvider] = {}
    _config: Optional[LLMConfig] = None
    _metrics: Optional[MetricsCollector] = None
    _cost_tracker: Optional[CostTracker] = None
    
    @classmethod
    def register_provider(cls, provider_type: ProviderType, provider_class: Type[LLMProvider]):
        """Register a custom provider"""
        cls._providers[provider_type] = provider_class
    
    @classmethod
    async def create(
        cls, 
        config: Optional[LLMConfig] = None,
        provider_type: Optional[ProviderType] = None
    ) -> LLMProvider:
        """
        Create or get cached provider instance.
        
        Args:
            config: Configuration object (uses env if not provided)
            provider_type: Override provider type from config
        """
        if not config:
            config = LLMConfig.from_env()
        cls._config = config
        
        # Initialize monitoring if enabled
        if config.enable_monitoring and not cls._metrics:
            cls._metrics = MetricsCollector()
        
        if config.enable_cost_tracking and not cls._cost_tracker:
            cls._cost_tracker = CostTracker()
        
        # Determine which provider to use
        active_provider = provider_type or config.get_active_provider()
        
        # Return cached instance if available
        if active_provider in cls._instances:
            provider = cls._instances[active_provider]
            if await provider.health_check():
                return cls._wrap_provider(provider)
        
        # Create new instance
        provider_class = cls._providers.get(active_provider)
        if not provider_class:
            raise ValueError(f"Unknown provider type: {active_provider}")
        
        provider_config = config.get_provider_config(active_provider)
        provider = provider_class(provider_config)
        
        try:
            await provider.initialize()
            cls._instances[active_provider] = provider
            logger.info(f"Initialized {active_provider.value} provider")
            return cls._wrap_provider(provider)
        
        except Exception as e:
            logger.error(f"Failed to initialize {active_provider.value}: {str(e)}")
            
            # Try fallback if configured
            if config.should_use_fallback(e):
                logger.info(f"Attempting fallback to {config.fallback_provider.value}")
                return await cls.create(config, config.fallback_provider)
            
            raise
    
    @classmethod
    def _wrap_provider(cls, provider: LLMProvider) -> LLMProvider:
        """Wrap provider with monitoring and fallback capabilities"""
        if not cls._config:
            return provider
        
        return MonitoredProvider(
            provider=provider,
            config=cls._config,
            metrics=cls._metrics,
            cost_tracker=cls._cost_tracker,
            factory=cls
        )
    
    @classmethod
    async def cleanup(cls):
        """Clean up all provider instances"""
        for provider in cls._instances.values():
            await provider.close()
        cls._instances.clear()
    
    @classmethod
    def get_metrics(cls) -> Optional[Dict[str, Any]]:
        """Get collected metrics"""
        if cls._metrics:
            return cls._metrics.get_summary()
        return None
    
    @classmethod
    def get_costs(cls) -> Optional[Dict[str, float]]:
        """Get cost tracking data"""
        if cls._cost_tracker:
            return cls._cost_tracker.get_summary()
        return None


class MonitoredProvider(LLMProvider):
    """
    Wrapper that adds monitoring, fallback, and caching to any provider.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        config: LLMConfig,
        metrics: Optional[MetricsCollector],
        cost_tracker: Optional[CostTracker],
        factory: LLMProviderFactory
    ):
        super().__init__(provider.config)
        self.provider = provider
        self.config = config
        self.metrics = metrics
        self.cost_tracker = cost_tracker
        self.factory = factory
    
    async def initialize(self) -> None:
        await self.provider.initialize()
    
    async def query(self, prompt: str, options: Optional[LLMOptions] = None):
        """Query with monitoring and fallback"""
        start_time = datetime.now()
        
        try:
            # Track request
            if self.metrics:
                self.metrics.record_request(self.provider.__class__.__name__)
            
            # Execute query
            result = await self.provider.query(prompt, options)
            
            # Track success
            if self.metrics:
                duration = (datetime.now() - start_time).total_seconds()
                self.metrics.record_success(self.provider.__class__.__name__, duration)
            
            # Track costs if not streaming
            if self.cost_tracker and isinstance(result, LLMResponse):
                cost = self.provider.estimate_cost(
                    result.usage.get("prompt_tokens", 0),
                    result.usage.get("completion_tokens", 0),
                    options.model if options else None
                )
                self.cost_tracker.record_cost(self.provider.__class__.__name__, cost)
            
            return result
        
        except Exception as e:
            # Track failure
            if self.metrics:
                self.metrics.record_failure(self.provider.__class__.__name__, str(e))
            
            # Try fallback if configured
            if self.config.should_use_fallback(e):
                logger.warning(f"Primary provider failed: {str(e)}, attempting fallback")
                fallback_provider = await self.factory.create(self.config, self.config.fallback_provider)
                return await fallback_provider.query(prompt, options)
            
            raise
    
    async def health_check(self) -> bool:
        return await self.provider.health_check()
    
    async def close(self) -> None:
        await self.provider.close()
    
    def supported_models(self):
        return self.provider.supported_models()
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model):
        return self.provider.estimate_cost(prompt_tokens, completion_tokens, model)


# Convenience function
async def get_provider(config: Optional[LLMConfig] = None) -> LLMProvider:
    """Get configured LLM provider instance"""
    return await LLMProviderFactory.create(config)


def get_batch_provider():
    """
    Return a :class:`BatchAnthropicProvider` if the ``ENABLE_BATCH_API`` env
    var is set to a truthy value, otherwise ``None``.

    VAL-25: Batch API support for cost optimisation.
    """
    if os.getenv("ENABLE_BATCH_API", "").lower() in ("1", "true"):
        from .providers.batch_provider import BatchAnthropicProvider
        return BatchAnthropicProvider()
    return None


# Context manager for automatic cleanup
@asynccontextmanager
async def llm_provider(config: Optional[LLMConfig] = None):
    """Context manager for LLM provider with automatic cleanup"""
    provider = await get_provider(config)
    try:
        yield provider
    finally:
        await provider.close()