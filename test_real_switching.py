#!/usr/bin/env python3
"""
Test final del switching real entre providers.
"""

import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_switching():
    """Test real provider switching"""
    print("=" * 60)
    print("🔄 Testing Real LLM Provider Switching")
    print("=" * 60)
    
    # Apply monkey patch
    from shared.llm.monkey_patch import apply_monkey_patch, switch_provider
    apply_monkey_patch()
    
    # Import the patched SDK
    from claude_agent_sdk import query, ClaudeAgentOptions
    
    # Test 1: Mock Provider
    print("\n1️⃣ Testing MOCK provider...")
    switch_provider("mock")
    
    options = ClaudeAgentOptions(model="sonnet", temperature=0.5, stream=True)
    result_gen = query("What is 1+1?", options)
    
    response = ""
    for chunk in result_gen:
        response += chunk
        print(chunk, end="", flush=True)
    
    print(f"\n   Full response: '{response.strip()}'")
    assert "mock" in response.lower(), "Mock provider should return mock response"
    print("   ✅ Mock provider works correctly!")
    
    # Test 2: Anthropic API (if available)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key and api_key.startswith("sk-ant-"):
        print("\n2️⃣ Testing ANTHROPIC_API provider...")
        switch_provider("anthropic_api", api_key=api_key)
        
        options = ClaudeAgentOptions(model="haiku", temperature=0.1, stream=True)
        result_gen = query("Just say 'test123' and nothing else.", options)
        
        response = ""
        for chunk in result_gen:
            response += chunk
            print(chunk, end="", flush=True)
        
        print(f"\n   Full response: '{response.strip()}'")
        assert len(response) > 0, "Anthropic should return a response"
        print("   ✅ Anthropic API works correctly!")
        
    else:
        print(f"\n2️⃣ Skipping Anthropic test (API key: {api_key[:12] if api_key else 'None'}...)")
    
    # Test 3: Environment variable switching
    print("\n3️⃣ Testing environment variable switching...")
    os.environ["LLM_PROVIDER"] = "mock"
    
    # Create new interceptor to pick up env change
    from shared.llm.monkey_patch import _interceptor
    _interceptor._initialize()  # Reinitialize with new env
    
    result_gen = query("Environment test", options)
    response = ""
    for chunk in result_gen:
        response += chunk
        print(chunk, end="", flush=True)
    
    print(f"\n   Environment switching response: '{response.strip()}'")
    assert "mock" in response.lower(), "Should use mock from environment"
    print("   ✅ Environment variable switching works!")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED - Provider switching works perfectly!")
    print("=" * 60)


if __name__ == "__main__":
    test_switching()