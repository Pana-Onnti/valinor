"""
Monkey patch para interceptar llamadas a claude_agent_sdk y redirigirlas
a nuestro sistema LLM provider. Esto permite switching sin tocar el código core.
"""

import os
import sys
import asyncio
from typing import AsyncIterator, Optional, Any, Dict
from pathlib import Path

# Add shared to path if needed
current_dir = Path(__file__).parent.parent.parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from shared.llm.base import LLMOptions, ModelType
from shared.llm.config import LLMConfig, ProviderType
from shared.llm.factory import get_provider


class ClaudeSDKInterceptor:
    """
    Interceptor que reemplaza las funciones de claude_agent_sdk
    con nuestro sistema de providers.
    """
    
    def __init__(self):
        self.provider = None
        self.config = None
        self._initialize()
    
    def _initialize(self):
        """Initialize provider based on environment"""
        try:
            provider_type = os.getenv("LLM_PROVIDER", "console_cli")

            if provider_type == "mock":
                self.config = LLMConfig(provider_type=ProviderType.MOCK)
            elif provider_type == "anthropic_api":
                self.config = LLMConfig(
                    provider_type=ProviderType.ANTHROPIC_API,
                    anthropic_config={
                        "api_key": os.getenv("ANTHROPIC_API_KEY"),
                        "timeout": 300,
                        "max_retries": 3,
                    },
                )
            else:
                # Default: console_cli — local `claude` CLI, no API key needed
                self.config = LLMConfig(
                    provider_type=ProviderType.CONSOLE_CLI,
                    cli_config={
                        "cli_path": os.getenv("CLAUDE_CLI_PATH", "claude"),
                        "timeout": int(os.getenv("CLAUDE_CLI_TIMEOUT", "300")),
                    },
                )

            print(f"🔄 LLM Provider: {self.config.provider_type.value}")

        except Exception as e:
            print(f"❌ Failed to initialize provider: {e}")
            self.config = LLMConfig(provider_type=ProviderType.MOCK)
    
    async def get_provider(self):
        """Get provider instance, creating if needed"""
        if not self.provider:
            from shared.llm.factory import get_provider
            self.provider = await get_provider(self.config)
        return self.provider
    
    async def query(self, prompt: str, options: Optional[Dict] = None) -> AsyncIterator[str]:
        """
        Drop-in replacement for claude_agent_sdk.query()
        """
        try:
            provider = await self.get_provider()
            
            # Convert options to our format
            llm_options = self._convert_options(options)
            
            # Execute query
            result = await provider.query(prompt, llm_options)
            
            # Handle different response types
            if hasattr(result, '__aiter__'):
                # Streaming response
                async for chunk in result:
                    yield chunk
            else:
                # Non-streaming response
                yield result.content
                
        except Exception as e:
            print(f"❌ Query failed: {e}")
            # Return error message as single chunk
            yield f"Error: {str(e)}"
    
    def _convert_options(self, options: Optional[Dict]) -> LLMOptions:
        """Convert claude_agent_sdk options to our format"""
        if not options:
            return LLMOptions()
        
        # Handle both dict and ClaudeAgentOptions object
        if hasattr(options, 'to_dict'):
            options = options.to_dict()
        elif hasattr(options, 'model'):
            # It's a ClaudeAgentOptions object, convert to dict
            options = {
                "model": getattr(options, "model", "sonnet"),
                "temperature": getattr(options, "temperature", 0.7),
                "max_tokens": getattr(options, "max_tokens", None),
                "stream": getattr(options, "stream", True),
                "system_prompt": getattr(options, "system_prompt", None),
                "tools": getattr(options, "tools", None)
            }
        
        # Map model names
        model_name = options.get("model", "sonnet")
        if model_name in ["sonnet", "claude-3-sonnet"]:
            model = ModelType.SONNET
        elif model_name in ["haiku", "claude-3-haiku"]:
            model = ModelType.HAIKU
        elif model_name in ["opus", "claude-3-opus"]:
            model = ModelType.OPUS
        else:
            model = ModelType.SONNET  # Default
        
        return LLMOptions(
            model=model,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens"),
            stream=options.get("stream", True),
            system_prompt=options.get("system_prompt"),
            tools=options.get("tools")
        )


# Global interceptor instance
_interceptor = ClaudeSDKInterceptor()


async def query(prompt: str, options=None):
    """
    Async generator — drop-in for claude_agent_sdk.query().

    Core agents use:  async for msg in query(prompt, options)
    They expect msg to be AssistantMessage with .content = [TextBlock(...)]

    We call the configured LLM provider, wrap the response in those objects,
    and yield one AssistantMessage per call.
    """
    try:
        provider = await _interceptor.get_provider()
        llm_options = _interceptor._convert_options(options)
        result = await provider.query(prompt, llm_options)

        if hasattr(result, "content"):
            # Non-streaming LLMResponse
            content = result.content
        elif hasattr(result, "__aiter__"):
            # Streaming — collect all chunks
            chunks = []
            async for chunk in result:
                chunks.append(str(chunk))
            content = "".join(chunks)
        else:
            content = str(result)

        yield AssistantMessage(content=[TextBlock(text=content)])

    except Exception as e:
        print(f"❌ query failed: {e}")
        yield AssistantMessage(content=[TextBlock(text=f"Error: {str(e)}")])


# Mock ClaudeAgentOptions for compatibility
class ClaudeAgentOptions:
    def __init__(self, model="sonnet", temperature=0.7, max_tokens=None, 
                 stream=True, system_prompt=None, tools=None, **kwargs):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.system_prompt = system_prompt
        self.tools = tools
        # Store any additional kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)
    
    def to_dict(self):
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
            "system_prompt": self.system_prompt,
            "tools": self.tools
        }


# Mock additional classes needed by core
class AssistantMessage:
    def __init__(self, content):
        self.content = content

class TextBlock:
    def __init__(self, text=""):
        self.text = text

def tool(*args, **kwargs):
    """Mock tool decorator — accepts any signature used by claude_agent_sdk"""
    def decorator(func):
        return func
    return decorator

def create_sdk_mcp_server(*args, **kwargs):
    """Mock MCP server creation"""
    class MockServer:
        def __init__(self):
            pass
        def start(self):
            pass
        def stop(self):
            pass
    return MockServer()


def apply_monkey_patch():
    """
    Apply monkey patch to replace claude_agent_sdk functions.
    Call this before importing any core valinor modules.
    """
    print("🐵 Applying claude_agent_sdk monkey patch...")
    
    # Create mock module
    import types
    mock_module = types.ModuleType('claude_agent_sdk')
    mock_module.query = query
    mock_module.ClaudeAgentOptions = ClaudeAgentOptions
    mock_module.AssistantMessage = AssistantMessage
    mock_module.TextBlock = TextBlock
    mock_module.tool = tool
    mock_module.create_sdk_mcp_server = create_sdk_mcp_server
    
    # Replace in sys.modules
    sys.modules['claude_agent_sdk'] = mock_module
    
    print("✅ Monkey patch applied successfully")


def switch_provider(provider_type: str, **config_kwargs):
    """
    Switch LLM provider at runtime.

    Args:
        provider_type: "console_cli" | "anthropic_api" | "mock"
        **config_kwargs: Additional config (e.g., api_key, cli_path)
    """
    global _interceptor

    print(f"🔄 Switching to provider: {provider_type}")
    os.environ["LLM_PROVIDER"] = provider_type

    if provider_type == "mock":
        _interceptor.config = LLMConfig(provider_type=ProviderType.MOCK)
    elif provider_type == "console_cli":
        _interceptor.config = LLMConfig(
            provider_type=ProviderType.CONSOLE_CLI,
            cli_config={
                "cli_path": config_kwargs.get("cli_path", os.getenv("CLAUDE_CLI_PATH", "claude")),
                "timeout": config_kwargs.get("timeout", 300),
            },
        )
    else:
        # Anthropic API
        api_key = config_kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
        _interceptor.config = LLMConfig(
            provider_type=ProviderType.ANTHROPIC_API,
            anthropic_config={
                "api_key": api_key,
                "timeout": config_kwargs.get("timeout", 300),
                "max_retries": config_kwargs.get("max_retries", 3)
            }
        )
    
    # Reset provider to force recreation
    _interceptor.provider = None
    
    print(f"✅ Switched to {provider_type}")


# Auto-apply patch when module is imported
apply_monkey_patch()