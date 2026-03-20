"""
Base abstraction for LLM providers following Liskov Substitution Principle.
All providers must implement this interface to ensure seamless switching.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum


class ModelType(str, Enum):
    """Standard model types across providers"""
    OPUS = "opus"
    SONNET = "sonnet" 
    HAIKU = "haiku"
    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo"


@dataclass
class LLMOptions:
    """Unified options for LLM queries across all providers"""
    model: ModelType = ModelType.SONNET
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = True
    system_prompt: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    stop_sequences: Optional[List[str]] = None
    metadata: Dict[str, Any] = None
    
    def to_anthropic(self) -> Dict[str, Any]:
        """Convert to Anthropic API format"""
        return {
            "model": self._map_model_to_anthropic(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens or 4096,
            "stream": self.stream,
            "system": self.system_prompt,
            "tools": self.tools,
            "stop_sequences": self.stop_sequences,
            "metadata": self.metadata
        }
    
    def to_console(self) -> Dict[str, Any]:
        """Convert to console/web interface format"""
        return {
            "model": self.model.value,
            "temperature": self.temperature,
            "maxTokens": self.max_tokens,
            "streaming": self.stream,
            "systemPrompt": self.system_prompt,
            "tools": self.tools,
            "stopSequences": self.stop_sequences,
            "metadata": self.metadata
        }
    
    def _map_model_to_anthropic(self) -> str:
        """Map generic model names to Anthropic-specific names"""
        mapping = {
            ModelType.OPUS: "claude-3-opus-20240229",
            ModelType.SONNET: "claude-3-5-sonnet-20241022",
            ModelType.HAIKU: "claude-3-haiku-20240307"
        }
        return mapping.get(self.model, "claude-3-5-sonnet-20241022")


@dataclass
class LLMResponse:
    """Unified response format from any LLM provider"""
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    raw_response: Optional[Any] = None


class LLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    Ensures consistent interface across different implementations.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._initialized = False
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the provider (auth, session setup, etc)"""
        pass
    
    @abstractmethod
    async def query(self, prompt: str, options: Optional[LLMOptions] = None) -> Union[LLMResponse, AsyncIterator[str]]:
        """
        Execute a query against the LLM.
        Returns LLMResponse for non-streaming, AsyncIterator for streaming.
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy and can accept requests"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (sessions, connections, etc)"""
        pass
    
    async def __aenter__(self):
        """Async context manager support"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup on context exit"""
        await self.close()
    
    def validate_options(self, options: LLMOptions) -> None:
        """Validate options are compatible with this provider"""
        if options.model not in self.supported_models():
            raise ValueError(f"Model {options.model} not supported by {self.__class__.__name__}")
    
    @abstractmethod
    def supported_models(self) -> List[ModelType]:
        """Return list of supported models for this provider"""
        pass
    
    @abstractmethod
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: ModelType) -> float:
        """Estimate cost for a query (for monitoring/budgeting)"""
        pass