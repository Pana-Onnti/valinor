"""
Adapter layer to make the new LLM abstraction compatible with existing Valinor code.
Drop-in replacement for claude_agent_sdk that uses our provider system.
"""

from typing import AsyncIterator, Optional
from .factory import get_provider
from .base import LLMOptions, ModelType
from .config import LLMConfig


# Global provider instance for backward compatibility
_global_provider = None


class ClaudeAgentOptions:
    """Backward compatible options class mimicking claude_agent_sdk"""

    def __init__(
        self,
        model: str = "sonnet",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = True,
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
        **kwargs
    ):
        # Map old model names to new enum
        model_mapping = {
            "sonnet": ModelType.SONNET,
            "haiku": ModelType.HAIKU,
            "opus": ModelType.OPUS,
            "claude-3-sonnet": ModelType.SONNET,
            "claude-3-haiku": ModelType.HAIKU,
            "claude-3-opus": ModelType.OPUS
        }

        self.options = LLMOptions(
            model=model_mapping.get(model, ModelType.SONNET),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            system_prompt=system_prompt,
            tools=tools
        )

        # Store any extra kwargs for compatibility
        self.extra = kwargs


async def query(
    prompt: str,
    options: Optional[ClaudeAgentOptions] = None
) -> AsyncIterator[str]:
    """
    Drop-in replacement for claude_agent_sdk.query().
    Maintains 100% API compatibility with existing Valinor agents.
    """
    global _global_provider

    # Initialize provider if needed
    if not _global_provider:
        config = LLMConfig.from_env()
        _global_provider = await get_provider(config)

    # Convert options
    llm_options = options.options if options else LLMOptions()

    # Execute query
    result = await _global_provider.query(prompt, llm_options)

    # Handle streaming vs non-streaming
    if isinstance(result, AsyncIterator):
        # Already an async iterator, return as-is
        async for chunk in result:
            yield chunk
    else:
        # Non-streaming response, convert to single-yield iterator
        yield result.content


async def create_agent(
    name: str,
    description: str,
    system_prompt: str,
    tools: Optional[list] = None,
    **kwargs
) -> "Agent":
    """
    Create an agent instance compatible with existing code.
    """
    return Agent(name, description, system_prompt, tools, **kwargs)


class Agent:
    """
    Agent class mimicking claude_agent_sdk.Agent for compatibility.
    """

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tools: Optional[list] = None,
        **kwargs
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tools = tools
        self.kwargs = kwargs
        self.provider = None

    async def __aenter__(self):
        """Async context manager entry"""
        config = LLMConfig.from_env()
        self.provider = await get_provider(config)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.provider:
            await self.provider.close()

    async def query(
        self,
        prompt: str,
        model: str = "sonnet",
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[str]:
        """Execute agent query"""
        options = ClaudeAgentOptions(
            model=model,
            temperature=temperature,
            system_prompt=self.system_prompt,
            tools=self.tools,
            **kwargs
        )

        async for chunk in query(prompt, options):
            yield chunk


# Re-export common names for compatibility
__all__ = [
    'query',
    'ClaudeAgentOptions',
    'create_agent',
    'Agent'
]


# Initialization function for explicit setup
async def initialize_provider(config: Optional[LLMConfig] = None):
    """
    Initialize the global provider explicitly.
    Useful for testing or when you want to control initialization.
    """
    global _global_provider
    _global_provider = await get_provider(config or LLMConfig.from_env())
    return _global_provider


# Cleanup function
async def cleanup():
    """Clean up global provider"""
    global _global_provider
    if _global_provider:
        await _global_provider.close()
        _global_provider = None
