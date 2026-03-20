#!/usr/bin/env python3
"""
Test script to demonstrate LLM provider switching capability.
Run with different configurations to see seamless switching.

Usage:
    # Test with Anthropic API
    LLM_PROVIDER=anthropic_api python test_provider_switch.py
    
    # Test with Console Auth
    LLM_PROVIDER=console_auth python test_provider_switch.py
    
    # Test with Mock (no credentials needed)
    LLM_PROVIDER=mock python test_provider_switch.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent))

from shared.llm import LLMConfig, ProviderType, get_provider
from shared.llm.adapter import query, ClaudeAgentOptions


async def test_direct_api():
    """Test using the new provider API directly"""
    print("\n=== Testing Direct Provider API ===")
    
    # Get config from environment
    config = LLMConfig.from_env()
    print(f"Active Provider: {config.get_active_provider().value}")
    print(f"Fallback Enabled: {config.enable_fallback}")
    if config.fallback_provider:
        print(f"Fallback Provider: {config.fallback_provider.value}")
    
    # Get provider
    provider = await get_provider(config)
    
    # Test non-streaming query
    print("\n--- Non-streaming Query ---")
    from shared.llm.base import LLMOptions, ModelType
    options = LLMOptions(
        model=ModelType.SONNET,
        temperature=0.5,
        stream=False,
        max_tokens=100
    )
    
    response = await provider.query(
        "What is 2+2? Answer in one number only.",
        options
    )
    
    if hasattr(response, 'content'):
        print(f"Response: {response.content}")
        if response.usage:
            print(f"Tokens used: {response.usage}")
    
    await provider.close()


async def test_backward_compatibility():
    """Test using the backward-compatible adapter (mimics claude_agent_sdk)"""
    print("\n=== Testing Backward Compatibility (Adapter) ===")
    
    # This is how existing Valinor code would use it
    options = ClaudeAgentOptions(
        model="sonnet",
        temperature=0.7,
        stream=True,
        max_tokens=150
    )
    
    print("--- Streaming Query (like existing agents) ---")
    response_text = ""
    async for chunk in query("Tell me a very short joke (max 20 words)", options):
        print(chunk, end="", flush=True)
        response_text += chunk
    
    print(f"\n\nTotal response length: {len(response_text)} chars")


async def test_provider_switching():
    """Demonstrate runtime provider switching"""
    print("\n=== Testing Provider Switching ===")
    
    providers_to_test = []
    
    # Determine which providers to test based on available credentials
    if os.getenv("LLM_PROVIDER") == "mock" or not os.getenv("ANTHROPIC_API_KEY"):
        print("Using MOCK provider (no API key detected)")
        providers_to_test = [ProviderType.MOCK]
    else:
        # Test available providers
        if os.getenv("ANTHROPIC_API_KEY"):
            providers_to_test.append(ProviderType.ANTHROPIC_API)
        if os.getenv("CLAUDE_USERNAME") and os.getenv("CLAUDE_PASSWORD"):
            providers_to_test.append(ProviderType.CONSOLE_AUTH)
        if not providers_to_test:
            providers_to_test = [ProviderType.MOCK]
    
    for provider_type in providers_to_test:
        print(f"\n--- Testing {provider_type.value} ---")
        
        config = LLMConfig(
            provider_type=provider_type,
            anthropic_config={"api_key": os.getenv("ANTHROPIC_API_KEY")},
            console_config={
                "username": os.getenv("CLAUDE_USERNAME"),
                "password": os.getenv("CLAUDE_PASSWORD")
            }
        )
        
        try:
            provider = await get_provider(config)
            
            # Quick health check
            is_healthy = await provider.health_check()
            print(f"Health Check: {'✓' if is_healthy else '✗'}")
            
            if is_healthy:
                from shared.llm.base import LLMOptions, ModelType
                response = await provider.query(
                    "Say 'Hello from [provider]' where [provider] is your name",
                    LLMOptions(stream=False, max_tokens=50)
                )
                
                if hasattr(response, 'content'):
                    print(f"Response: {response.content[:100]}")
            
            await provider.close()
            
        except Exception as e:
            print(f"Error with {provider_type.value}: {str(e)}")


async def test_fallback_mechanism():
    """Test automatic fallback on failure"""
    print("\n=== Testing Fallback Mechanism ===")
    
    # Configure with fallback
    config = LLMConfig(
        provider_type=ProviderType.ANTHROPIC_API,  # Primary
        enable_fallback=True,
        fallback_provider=ProviderType.MOCK,  # Fallback to mock
        anthropic_config={
            "api_key": "invalid-key-to-trigger-fallback"  # Bad key
        }
    )
    
    print(f"Primary: {config.provider_type.value}")
    print(f"Fallback: {config.fallback_provider.value}")
    
    try:
        # This should fail on Anthropic and fallback to Mock
        provider = await get_provider(config)
        response = await provider.query(
            "Testing fallback",
            None
        )
        
        if hasattr(response, 'content'):
            print(f"Got response (via fallback): {response.content}")
        
        await provider.close()
        
    except Exception as e:
        print(f"Fallback test error: {str(e)}")


async def test_metrics_and_costs():
    """Test monitoring and cost tracking"""
    print("\n=== Testing Metrics and Cost Tracking ===")
    
    from shared.llm.factory import LLMProviderFactory
    
    config = LLMConfig(
        provider_type=ProviderType.MOCK,
        enable_monitoring=True,
        enable_cost_tracking=True
    )
    
    provider = await get_provider(config)
    
    # Run a few queries
    for i in range(3):
        await provider.query(f"Query {i+1}", None)
    
    # Get metrics
    metrics = LLMProviderFactory.get_metrics()
    if metrics:
        print("\nMetrics:")
        for provider_name, stats in metrics.get("providers", {}).items():
            print(f"  {provider_name}:")
            print(f"    Total Requests: {stats.get('total_requests', 0)}")
            print(f"    Success Rate: {stats.get('success_rate', 0):.1f}%")
    
    # Get costs
    costs = LLMProviderFactory.get_costs()
    if costs:
        print(f"\nTotal Cost: ${costs.get('total_cost', 0):.4f}")
    
    await LLMProviderFactory.cleanup()


async def main():
    """Run all tests"""
    print("=" * 60)
    print("LLM Provider Switching Test Suite")
    print("=" * 60)
    
    # Show current configuration
    print("\nEnvironment Configuration:")
    print(f"  LLM_PROVIDER: {os.getenv('LLM_PROVIDER', 'not set')}")
    print(f"  ANTHROPIC_API_KEY: {'set' if os.getenv('ANTHROPIC_API_KEY') else 'not set'}")
    print(f"  CLAUDE_USERNAME: {'set' if os.getenv('CLAUDE_USERNAME') else 'not set'}")
    
    try:
        # Run tests
        await test_direct_api()
        await test_backward_compatibility()
        await test_provider_switching()
        await test_fallback_mechanism()
        await test_metrics_and_costs()
        
        print("\n" + "=" * 60)
        print("✅ All tests completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        from shared.llm.factory import LLMProviderFactory
        await LLMProviderFactory.cleanup()


if __name__ == "__main__":
    asyncio.run(main())